"""
extractor.py — FASE 1 de DesignLens

Este archivo se encarga de UNA sola cosa: dado un archivo .cdr,
sacar de adentro las imágenes de vista previa (las que CorelDRAW
guarda internamente para mostrar el "thumbnail" del diseño).

Por qué funciona: un .cdr de CorelDRAW 2020 es, por dentro, un archivo ZIP.
Verificado con un archivo real que la carpeta interna es "metadata/thumbnails/"
y los previews vienen en formato .bmp (no .png como se pensaba al inicio).
Por eso este código también convierte cada .bmp a .png con Pillow,
para que el resto del proyecto (CLIP, la interfaz web) trabaje siempre
con un formato consistente.
"""

import zipfile
from pathlib import Path
from PIL import Image
import io

# Esta carpeta es donde vamos a guardar copias de los previews extraídos
# (ya convertidos a PNG), para no tener que volver a abrir el .cdr cada vez.
CACHE_DIR = Path("thumbnails_cache")

# Carpeta real adentro del .cdr donde están los previews.
# La confirmamos con debug_zip.py: es "metadata/thumbnails/", no "previews/".
CARPETA_PREVIEWS = "metadata/thumbnails/"


def extraer_previews(ruta_cdr: str) -> list[dict]:
    """
    Recibe la ruta de un archivo .cdr y devuelve una lista de diccionarios,
    uno por cada preview encontrado adentro.

    Cada diccionario tiene:
        - "pagina": número de página (0 = thumbnail general del doc, 1..N = páginas)
        - "ruta_cache": dónde quedó guardada la copia del preview (ya en .png) en thumbnails_cache/

    Si el .cdr no tiene la carpeta de previews (por ejemplo, versiones muy
    viejas de CorelDRAW que no son ZIP), devolvemos una lista vacía en vez
    de reventar con un error — así el indexador puede seguir con el siguiente archivo.
    """
    ruta_cdr = Path(ruta_cdr)
    resultados = []

    # Nos aseguramos de que exista la carpeta de cache antes de escribir ahí.
    CACHE_DIR.mkdir(exist_ok=True)

    # Este bloque intenta abrir el .cdr como si fuera un ZIP.
    # Si el archivo está corrupto o no es realmente un ZIP (versión vieja),
    # zipfile lanza BadZipFile — lo capturamos para no detener todo el proceso.
    try:
        with zipfile.ZipFile(ruta_cdr, "r") as zf:
            # Listamos todas las entradas del ZIP y nos quedamos solo
            # con las que están dentro de "metadata/thumbnails/" y son imágenes.
            entradas_preview = [
                nombre for nombre in zf.namelist()
                if nombre.startswith(CARPETA_PREVIEWS)
                and nombre.lower().endswith((".bmp", ".png"))
            ]

            if not entradas_preview:
                print(f"⚠️  {ruta_cdr.name}: no se encontraron previews adentro.")
                return resultados

            for nombre_entrada in entradas_preview:
                # nombre_entrada es algo como "metadata/thumbnails/page1.bmp"
                # o "metadata/thumbnails/thumbnail.bmp"
                nombre_archivo_interno = Path(nombre_entrada).stem  # "page1" o "thumbnail"

                # Determinamos el número de página a partir del nombre.
                # "thumbnail" lo tratamos como página 0 (vista general del documento).
                if nombre_archivo_interno == "thumbnail":
                    numero_pagina = 0
                else:
                    # Sacamos solo los dígitos de algo como "page3" -> 3
                    digitos = "".join(c for c in nombre_archivo_interno if c.isdigit())
                    numero_pagina = int(digitos) if digitos else 0

                # Construimos un nombre único para la copia en cache, para que
                # dos .cdr distintos no se pisen el archivo (ej: "diseño1__page1.png")
                nombre_cache = f"{ruta_cdr.stem}__page{numero_pagina}.png"
                ruta_destino = CACHE_DIR / nombre_cache

                # Leemos los bytes del preview desde dentro del ZIP.
                with zf.open(nombre_entrada) as origen:
                    datos_imagen = origen.read()

                # Abrimos esos bytes con Pillow (funciona igual venga en .bmp o .png)
                # y lo guardamos siempre como .png en el cache, para tener un
                # formato único en todo el proyecto sin importar qué formato
                # use internamente cada versión de CorelDRAW.
                imagen = Image.open(io.BytesIO(datos_imagen))
                imagen.save(ruta_destino, "PNG")

                resultados.append({
                    "pagina": numero_pagina,
                    "ruta_cache": str(ruta_destino),
                })

    except zipfile.BadZipFile:
        print(f"❌ {ruta_cdr.name}: no es un ZIP válido (posible .cdr de versión antigua o corrupto).")
    except FileNotFoundError:
        print(f"❌ {ruta_cdr.name}: el archivo no existe en esa ruta.")

    return resultados


# Este bloque solo se ejecuta si corremos "python app/extractor.py" directamente
# (no se ejecuta si otro archivo importa este módulo). Es nuestra prueba rápida.
if __name__ == "__main__":
    ruta_prueba = r"D:\DISEÑO 2026\7 logos diseño PASAR PHOTOSHOP 1ero.cdr"
    previews = extraer_previews(ruta_prueba)

    print(f"\n✅ Se extrajeron {len(previews)} preview(s):")
    for p in previews:
        print(f"  Página {p['pagina']} -> {p['ruta_cache']}")