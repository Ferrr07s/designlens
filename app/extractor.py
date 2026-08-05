"""
extractor.py — FASE 1 de DesignLens

Este archivo se encarga de UNA sola cosa: dado un archivo .cdr,
sacar de adentro las imágenes de vista previa (las que CorelDRAW
guarda internamente para mostrar el "thumbnail" del diseño).

Por qué funciona: un .cdr de CorelDRAW 2020 es, por dentro, un archivo ZIP.

IMPORTANTE — descubrimos que existen DOS formatos distintos de .cdr
en la colección real, probablemente por distintas versiones o formas
de guardado de CorelDRAW:

  Formato A: carpeta "metadata/thumbnails/", archivos .bmp
  Formato B: carpeta "previews/", archivos .png

Por eso este código prueba ambas rutas, en ese orden, y usa la que
encuentre resultados. Así soportamos ambos tipos de archivo sin tener
que saber de antemano cuál es cuál.
"""

import zipfile
from pathlib import Path
from PIL import Image
import io

# Esta carpeta es donde vamos a guardar copias de los previews extraídos
# (ya convertidos a PNG), para no tener que volver a abrir el .cdr cada vez.
CACHE_DIR = Path("thumbnails_cache")

# Las dos rutas posibles donde CorelDRAW guarda los previews,
# según el formato/versión con que se guardó el archivo.
CARPETAS_PREVIEWS_POSIBLES = [
    "metadata/thumbnails/",  # Formato A (.bmp)
    "previews/",              # Formato B (.png)
]


def _buscar_entradas_preview(todas_las_entradas: list[str]) -> list[str]:
    """
    Recibe la lista completa de entradas del ZIP y prueba cada carpeta
    de preview conocida, en orden, hasta encontrar una que tenga
    resultados. Devuelve la lista de entradas encontradas (puede
    estar vacía si el archivo no usa ninguno de los formatos conocidos).
    """
    for carpeta in CARPETAS_PREVIEWS_POSIBLES:
        entradas = [
            nombre for nombre in todas_las_entradas
            if nombre.startswith(carpeta)
            and nombre.lower().endswith((".bmp", ".png"))
        ]
        if entradas:
            return entradas
    return []


def extraer_previews(ruta_cdr: str) -> list[dict]:
    """
    Recibe la ruta de un archivo .cdr y devuelve una lista de diccionarios,
    uno por cada preview encontrado adentro.

    Cada diccionario tiene:
        - "pagina": número de página (0 = thumbnail general del doc, 1..N = páginas)
        - "ruta_cache": dónde quedó guardada la copia del preview (ya en .png) en thumbnails_cache/

    Si el .cdr no tiene ninguna de las carpetas de preview conocidas,
    devolvemos una lista vacía en vez de reventar con un error — así
    el indexador puede seguir con el siguiente archivo.
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
            todas_las_entradas = zf.namelist()

            # Probamos las carpetas de preview conocidas en orden,
            # y usamos la primera que tenga resultados.
            entradas_preview = _buscar_entradas_preview(todas_las_entradas)

            if not entradas_preview:
                print(f"⚠️  {ruta_cdr.name}: no se encontraron previews adentro (ningún formato conocido).")
                return resultados

            for nombre_entrada in entradas_preview:
                # nombre_entrada es algo como "metadata/thumbnails/page1.bmp"
                # o "previews/page1.png"
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
    ruta_prueba = r"D:\DISEÑO 2026\huntryx morado diseño.cdr"
    previews = extraer_previews(ruta_prueba)

    print(f"\n✅ Se extrajeron {len(previews)} preview(s):")
    for p in previews:
        print(f"  Página {p['pagina']} -> {p['ruta_cache']}")