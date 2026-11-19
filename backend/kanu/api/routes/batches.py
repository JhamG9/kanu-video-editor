"""Tandas y subida de archivos (videos, pares de estilo, LUT)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from kanu import config
from kanu.core import style
from kanu.services import batches, library

from ..state import runner

from ..body import json_body

router = APIRouter(prefix="/api", tags=["batches"])


@router.get("/batch")
def batch_state():
    return {"state": runner.state, "options": batches.BATCH_OPTIONS, "batches": batches.batches()[:20]}


@router.post("/batch")
def batch_start(body: dict = Depends(json_body)):
    names = [library.safe_video_name(n) for n in body["clips"]]
    for n in names:
        library.clip_path(n)  # que existan
    return runner.start(names, body.get("options", {}), body.get("note", ""), body.get("title", ""),
                        body.get("process", True))


@router.put("/upload")
async def upload(request: Request, name: str, dest: str = "videos"):
    """Sube un archivo tal cual (sin cargarlo en memoria) a Videos/, al estilo o como LUT."""
    n = int(request.headers.get("content-length") or 0)
    if dest == "estilo_lut":                     # LUT propia: siempre estilo/lut.cube
        if not name.lower().endswith(".cube"):
            return JSONResponse({"error": "La LUT debe ser un archivo .cube"}, status_code=400)
        fname, folder = "lut.cube", style.DIR
    else:
        fname = library.safe_video_name(name)
        folder = {"videos": config.VIDEOS, "estilo_original": style.ORIG, "estilo_editado": style.EDIT}[dest]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / fname
    if dest != "videos" and target.exists():      # en el estilo, subir de nuevo reemplaza
        target.unlink()
    if target.exists() and target.stat().st_size == n:
        async for _ in request.stream():          # ya está: no se sube dos veces
            pass
        return {"name": fname, "skipped": True}
    if target.exists():
        i = 2
        while (folder / f"{target.stem}_{i}{target.suffix}").exists():
            i += 1
        target = folder / f"{target.stem}_{i}{target.suffix}"
    tmp = target.with_name(target.name + ".parcial")
    got = 0
    with open(tmp, "wb") as fh:
        async for chunk in request.stream():
            fh.write(chunk)
            got += len(chunk)
    if n and got != n:
        tmp.unlink(missing_ok=True)
        return JSONResponse({"error": "la subida se cortó"}, status_code=400)
    tmp.replace(target)
    return {"name": target.name, "skipped": False}
