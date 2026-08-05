"""
config.py — Configuración central de DesignLens

Este archivo lee las variables sensibles (contraseñas, rutas) desde el
archivo .env en vez de tenerlas escritas directamente en el código.
Así, el código fuente que subimos a GitHub nunca expone la contraseña
real de MySQL ni la ruta privada de tus diseños.
"""

import os
from dotenv import load_dotenv

# Esta línea busca el archivo .env en la raíz del proyecto y carga
# sus variables como si fueran variables de entorno del sistema.
load_dotenv()

# Cada os.getenv() lee una variable del .env. El segundo argumento
# (cuando existe) es un valor por defecto, por si esa variable falta.
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "designlens")

# Ruta de la carpeta que vamos a indexar (tus diseños reales).
DESIGN_FOLDER = os.getenv("DESIGN_FOLDER")