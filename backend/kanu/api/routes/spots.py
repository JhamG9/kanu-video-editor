"""Manchas del sensor."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from kanu.core import spots
from kanu.services import library, previews

router = APIRouter(prefix="/api/spot", tags=["spots"])


@router.post("/measure")
def measure(clip: str, x: float, y: float, r: float = 40):
    sp = spots.measure_spot(library.clip_path(clip), library.meta(clip), x, y, r)
    if not sp:
        return JSONResponse({"error": "Ahí no encontré una mancha de sensor. Haz clic justo encima."}, status_code=404)
    return sp


@router.post("/prepare")
def prepare(clip: str):
    previews.prepare_clean(clip)
    return library.clip_info(clip)
