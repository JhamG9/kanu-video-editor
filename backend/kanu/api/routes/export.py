"""Exportación, cola de trabajos y espacio en disco."""
import subprocess
import sys

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
    folder = config.SUBIR if config.SUBIR.exists() else config.EXPORT
    opener = {"darwin": "open", "win32": "explorer"}.get(sys.platform, "xdg-open")
    subprocess.run([opener, str(folder)])
    return {"ok": True}
