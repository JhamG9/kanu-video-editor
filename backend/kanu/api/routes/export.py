"""Exportación, cola de trabajos y espacio en disco."""
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from kanu import config
from kanu.services import library

from ..state import exporter

from ..body import json_body

router = APIRouter(prefix="/api", tags=["export"])


@router.post("/export")
def export(body: dict = Depends(json_body)):
    ids = exporter.add(body["clips"], body["presets"], body.get("audio", False), body.get("upload", False))
    return {"added": len(ids)}


@router.get("/jobs")
def jobs():
    return exporter.list()


@router.post("/jobs/clear")
def jobs_clear():
    exporter.clear_done()
    return {"ok": True}


@router.post("/jobs/cancel")
def jobs_cancel():
    exporter.cancel_all()
    return {"ok": True}


@router.get("/cache")
def cache():
    return {"bytes": library.cache_size()}


@router.post("/cache/clean")
def cache_clean():
    if any(j["status"] in ("procesando", "estabilizando") for j in exporter.list()):
        return JSONResponse({"error": "Espera a que termine la exportación"}, status_code=409)
    return {"freed": library.clean_cache()}


@router.post("/open-exports")
def open_exports():
    folder = config.subir_dir()
    if not folder.exists():
        folder = folder if config.prefs().get("export_dir") else config.EXPORT
    folder.mkdir(parents=True, exist_ok=True)
    opener = {"darwin": "open", "win32": "explorer"}.get(sys.platform, "xdg-open")
    subprocess.run([opener, str(folder)])
    return {"ok": True}


def _export_dir_info():
    return {"path": str(config.subir_dir()), "default": str(config.SUBIR),
            "custom": bool(config.prefs().get("export_dir"))}


@router.get("/export-dir")
def export_dir():
    return _export_dir_info()


@router.post("/export-dir/choose")
def export_dir_choose():
    """Abre el selector de carpetas de macOS y guarda la elegida como carpeta de exportación."""
    if sys.platform != "darwin":
        return JSONResponse({"error": "El selector de carpetas solo está disponible en Mac"}, status_code=400)
    start = config.subir_dir() if config.subir_dir().exists() else Path.home()
    script = ['-e', 'activate',
              '-e', f'set f to choose folder with prompt "Carpeta donde Kanu guarda los videos exportados" '
                    f'default location (POSIX file "{start}")',
              '-e', 'POSIX path of f']
    r = subprocess.run(["osascript", *script], capture_output=True, text=True)
    if r.returncode != 0:                      # el usuario canceló
        return {**_export_dir_info(), "cancelled": True}
    folder = Path(r.stdout.strip()).expanduser()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".kanu_prueba"
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        return JSONResponse({"error": f"No puedo escribir en {folder}"}, status_code=400)
    config.set_pref("export_dir", None if folder.resolve() == config.SUBIR.resolve() else str(folder))
    return _export_dir_info()


@router.post("/export-dir/reset")
def export_dir_reset():
    config.set_pref("export_dir", None)
    return _export_dir_info()
