"""Imágenes y videos para el visor: fotogramas, recortes al 100 %, copias de reproducción."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from kanu.infra import ffmpeg as ff
from kanu.services import library, previews

from ..files import send_file

router = APIRouter(prefix="/api", tags=["media"])


@router.get("/frame")
def frame(clip: str, t: float = 0, w: int = 1920, orig: str = "0"):
    m = library.meta(clip)
    t = round(min(max(t, 0), m["duration"] - 0.05), 2)
    big = w > 400 and orig != "1"
    src, _ = previews.preview_source(clip) if big else (library.clip_path(clip), None)
    fm = m
    if big:                                         # con reducción de ruido: el fotograma sale de su copia
        dn = previews.denoised_proxy_ready(clip)
        if dn:
            src, fm = dn, {}                        # la copia ya tiene los superblancos tratados
        elif ff.DENOISE.get(library.load(clip).get("denoise", "off")):
            previews.prepare_proxy(clip)
    f = library.config.CACHE / "frames" / f"{src.stem}_v2_{w}_{t:.2f}.jpg"
    if not f.exists():
        f.write_bytes(ff.frame_jpeg(src, t, fm, w))
    return Response(f.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@router.get("/crop")
def crop(clip: str, t: float, cx: float, cy: float, dn: str = "off"):
    p, m = previews.preview_source(clip)[0], library.meta(clip)
    return Response(ff.crop_png(p, t, cx, cy, m, dn), media_type="image/png")


@router.get("/proxy")
def proxy(clip: str, request: Request):
    return send_file(previews.proxy_file(clip), "video/mp4", request)


@router.post("/proxy/prepare")
def proxy_prepare(clip: str):
    previews.prepare_proxy(clip)
    return {"ok": True}


@router.get("/compare")
def compare(clip: str, request: Request):
    f = previews.compare_file(clip)
    if not f:
        return JSONResponse({"error": "todavía no hay comparación"}, status_code=404)
    return send_file(f, "video/mp4", request)


@router.post("/stabilize")
def stabilize(clip: str):
    previews.prepare_stab(clip)
    return library.clip_info(clip)
