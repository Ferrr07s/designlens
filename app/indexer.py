"""
indexer.py — FASE 2 de DesignLens

Este archivo recorre la carpeta de diseños, y para cada .cdr:
  1. Revisa si ya está indexado y sin cambios (indexado incremental).
  2. Si es nuevo o cambió, extrae sus previews (usando extractor.py),
     genera un "embedding" (vector numérico) de cada imagen con CLIP,
     y lo guarda en MySQL.
  3. Al final, borra de la base de datos los registros de archivos
     que ya no existen en disco (por si borraste o moviste un .cdr).

Qué es un "embedding": es una lista de ~512 números que representa
el CONTENIDO VISUAL de una imagen. Dos imágenes parecidas visualmente
tienen embeddings parecidos (números cercanos entre sí). Eso es lo que
nos permite luego "buscar por foto" en la Fase 3.

Nota sobre archivos sin preview: algunos .cdr fueron guardados con un
método/versión distinta de CorelDRAW y no tienen la carpeta interna
de previews que sabemos leer. Para esos casos, en vez de reintentarlos
en cada corrida (desperdiciando tiempo), guardamos un registro
"marcador" con page_number = -1, así el sistema recuerda que ya lo
intentó y solo lo reintenta si el archivo realmente cambia.
"""

import json
import time
from pathlib import Path

import mysql.connector
from sentence_transformers import SentenceTransformer
from PIL import Image

from app import config
from app.extractor import extraer_previews

# Cargamos el modelo CLIP UNA sola vez al iniciar el script.
# Cargarlo es lo más pesado (tarda unos segundos y usa ~600 MB de RAM),
# por eso no lo hacemos dentro del loop de archivos.
print("Cargando modelo CLIP (puede tardar un momento la primera vez)...")
modelo_clip = SentenceTransformer("clip-ViT-B-32")
print("Modelo cargado.\n")


def conectar_bd():
    """
    Abre una conexión a MySQL usando las credenciales del .env
    (a través de config.py). La cerramos manualmente donde se use.
    """
    return mysql.connector.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )


def obtener_mtime_guardado(cursor, file_path: str) -> float | None:
    """
    Busca en la BD si ya existe algún registro para este file_path,
    y devuelve el file_mtime guardado la última vez que se indexó.
    Si no existe ningún registro, devuelve None (archivo nunca indexado).

    Esto es la base del "indexado incremental": si el mtime actual del
    disco es igual al guardado, significa que el archivo no cambió
    desde la última vez, así que podemos saltarlo sin re-procesar.

    Gracias al registro "marcador" (page_number = -1), esto también
    funciona para archivos sin preview: una vez marcados, ya no se
    vuelven a reintentar en cada corrida.
    """
    cursor.execute(
        "SELECT file_mtime FROM designs WHERE file_path = %s LIMIT 1",
        (file_path,),
    )
    fila = cursor.fetchone()
    return fila[0] if fila else None


def indexar_archivo(cursor, ruta_cdr: Path):
    """
    Procesa UN archivo .cdr completo: extrae sus previews, genera
    embeddings, y guarda/actualiza las filas correspondientes en MySQL.

    Si el archivo NO tiene previews (formato alterno de CorelDRAW),
    igual guardamos un registro "marcador" con page_number = -1,
    para que el sistema recuerde que ya lo intentó y no lo reintente
    en cada corrida — solo lo reintentará si el archivo cambia de verdad.
    """
    file_path = str(ruta_cdr)
    file_mtime = ruta_cdr.stat().st_mtime  # fecha de última modificación

    # 1. Extraemos los previews usando el extractor de la Fase 1.
    previews = extraer_previews(file_path)

    # 2. Antes de insertar los nuevos, borramos cualquier fila vieja de
    #    este mismo archivo (incluyendo un posible marcador anterior).
    #    Esto evita que queden páginas "fantasma" si, por ejemplo,
    #    el .cdr antes tenía 5 páginas y ahora tiene 3.
    cursor.execute("DELETE FROM designs WHERE file_path = %s", (file_path,))

    if not previews:
        # No se encontraron previews (formato alterno de CorelDRAW,
        # ej: archivos exportados en v14.0 o guardados de otra forma).
        # Guardamos un marcador para "recordar" que ya lo intentamos,
        # sin necesidad de embedding ni thumb (van como NULL).
        cursor.execute(
            """
            INSERT INTO designs
                (file_path, file_name, page_number, thumb_path, file_mtime, embedding)
            VALUES (%s, %s, -1, NULL, %s, NULL)
            """,
            (file_path, ruta_cdr.name, file_mtime),
        )
        return

    # 3. Por cada preview, generamos su embedding CLIP y lo guardamos.
    for preview in previews:
        imagen = Image.open(preview["ruta_cache"])

        # Esta línea es la que "convierte" la imagen en un vector de números.
        # .tolist() lo pasa de un array de numpy a una lista normal de Python,
        # para poder guardarlo como JSON en MySQL.
        embedding = modelo_clip.encode(imagen).tolist()

        cursor.execute(
            """
            INSERT INTO designs
                (file_path, file_name, page_number, thumb_path, file_mtime, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                file_path,
                ruta_cdr.name,
                preview["pagina"],
                preview["ruta_cache"],
                file_mtime,
                json.dumps(embedding),
            ),
        )

    print(f"✅ Indexado: {ruta_cdr.name} ({len(previews)} página(s))")


def limpiar_archivos_borrados(cursor, rutas_actuales_en_disco: set[str]):
    """
    Compara qué file_path existen en la BD contra los que existen
    ahora mismo en disco, y borra de la BD los que ya no están
    (el usuario borró o movió ese .cdr).
    """
    cursor.execute("SELECT DISTINCT file_path FROM designs")
    rutas_en_bd = {fila[0] for fila in cursor.fetchall()}

    rutas_a_borrar = rutas_en_bd - rutas_actuales_en_disco

    for ruta in rutas_a_borrar:
        cursor.execute("DELETE FROM designs WHERE file_path = %s", (ruta,))
        print(f"🗑️  Eliminado de la BD (ya no existe en disco): {Path(ruta).name}")


def ejecutar_indexado(limite: int | None = None):
    """
    Función principal: recorre la carpeta configurada en .env,
    indexa cada .cdr (saltando los que no cambiaron), y al final
    limpia los registros de archivos borrados.

    limite: si se pasa un número, solo procesa esa cantidad de archivos
    nuevos/modificados. Útil para pruebas rápidas antes de correr
    contra toda la carpeta real.
    """
    carpeta = Path(config.DESIGN_FOLDER)

    if not carpeta.exists():
        print(f"❌ La carpeta configurada no existe: {carpeta}")
        return

    # Buscamos todos los .cdr dentro de la carpeta (y subcarpetas, con **/*.cdr)
    archivos_cdr = list(carpeta.glob("**/*.cdr"))
    print(f"📂 Se encontraron {len(archivos_cdr)} archivo(s) .cdr en {carpeta}\n")

    conexion = conectar_bd()
    cursor = conexion.cursor()

    procesados = 0
    saltados = 0

    for ruta_cdr in archivos_cdr:
        file_mtime_actual = ruta_cdr.stat().st_mtime
        mtime_guardado = obtener_mtime_guardado(cursor, str(ruta_cdr))

        if mtime_guardado is not None and mtime_guardado == file_mtime_actual:
            # No cambió desde la última vez, lo saltamos.
            saltados += 1
            continue

        indexar_archivo(cursor, ruta_cdr)
        conexion.commit()  # guardamos cambios de este archivo antes de seguir
        procesados += 1

        if limite is not None and procesados >= limite:
            print(f"\n⏸️  Límite de {limite} archivo(s) alcanzado, deteniendo esta corrida.")
            break

    # Solo limpiamos archivos borrados si NO usamos límite,
    # porque con límite no recorrimos toda la carpeta y borraríamos
    # por error archivos válidos que todavía no llegamos a revisar.
    if limite is None:
        rutas_actuales = {str(r) for r in archivos_cdr}
        limpiar_archivos_borrados(cursor, rutas_actuales)
        conexion.commit()

    cursor.close()
    conexion.close()

    print(f"\n📊 Resumen: {procesados} procesado(s), {saltados} sin cambios (saltados).")


if __name__ == "__main__":
    # Ya validamos que el extractor y el indexador funcionan bien.
    # Ahora corremos sin límite, contra toda la carpeta real.
    ejecutar_indexado(limite=None)