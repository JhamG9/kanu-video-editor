"""Clips: lista, ajustes, corrección automática, enderezar y color."""
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from kanu.core import grade
from kanu.infra import ffmpeg as ff
from kanu.infra import gyroflow
from kanu.services import library

from ..body import json_body

router = APIRouter(prefix="/api", tags=["clips"])


@router.get("/clips")
def list_clips():
    return {"clips": [library.clip_info(n) for n in library.clips()],
            "presets": {k: v["label"] for k, v in ff.PRESETS.items()},
            "denoise": ff.DENOISE_LABEL, "stab_levels": gyroflow.LABELS,
            "stab_methods": gyroflow.METHODS, "stab_available": gyroflow.available()}


@router.get("/clip")
def get_clip(clip: str):
    return library.clip_info(clip)


@router.post("/settings")
def save_settings(clip: str, settings: dict = Depends(json_body)):
    library.save(clip, settings)
    return library.clip_info(clip)


@router.post("/auto")
def auto(clip: str):
    library.auto(clip)
    return library.clip_info(clip)


@router.post("/straighten")
def straighten(clip: str):
    s, msg = library.straighten(clip)
    library.save(clip, s)
    info = library.clip_info(clip)
    info["message"] = msg
    return info


@router.post("/lut")
def lut(settings: dict = Depends(json_body)):
    return Response(grade.lut_bytes(settings), media_type="application/octet-stream")
