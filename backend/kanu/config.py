"""Rutas y programas externos de Kanu, en un solo lugar.

KANU_DATA: carpeta de datos del usuario (videos, ajustes, finales, estilo). Por ahora es la raíz del
proyecto; la app de escritorio la moverá a una carpeta propia (p. ej. ~/Movies/Kanu).
KANU_FFMPEG / KANU_FFPROBE / KANU_GYROFLOW: rutas a los programas, para empaquetarlos con la app.
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]                # raíz del repositorio
DATA = Path(os.environ.get("KANU_DATA", ROOT)).expanduser()

VIDEOS = DATA / "Videos"
AJUSTES = DATA / "ajustes"
CACHE = DATA / ".cache"
SUBIR = DATA / "videos subir"     # finales listos para subir a los bancos de stock
TANDAS = DATA / "tandas"          # una ficha .json por tanda: opciones y nota
EXPORT = DATA / "Exportados"
ESTILO = DATA / "estilo"          # mi estilo de color

VIDEO_EXT = {".mp4", ".mov", ".mxf", ".m4v"}


def _bin(env, name, fallback):
    return os.environ.get(env) or shutil.which(name) or fallback


FFMPEG = _bin("KANU_FFMPEG", "ffmpeg", "/opt/homebrew/bin/ffmpeg")
FFPROBE = _bin("KANU_FFPROBE", "ffprobe", "/opt/homebrew/bin/ffprobe")
GYROFLOW = os.environ.get("KANU_GYROFLOW", "/Applications/Gyroflow.app/Contents/MacOS/gyroflow")

for d in (VIDEOS, AJUSTES, CACHE / "frames", CACHE / "luts", EXPORT):
    d.mkdir(parents=True, exist_ok=True)
