"""Mi estilo de color."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from kanu.core import style

from ..body import json_body

router = APIRouter(prefix="/api/style", tags=["style"])


@router.get("")
def status():
    return style.status()


@router.post("/learn")
def learn():
    style.learn()
    return style.status()


@router.post("/config")
def set_config(body: dict = Depends(json_body)):
    style.set_config(**body)
    return style.status()


@router.post("/delete")
def delete(name: str | None = None, all: str = "0"):   # noqa: A002 - "all" es el nombre del parámetro en la URL
    if all == "1":                                     # todo solo si se pide explícitamente
        style.delete(None)
    elif name:
        style.delete(name)
    else:
        return JSONResponse({"error": "falta qué borrar"}, status_code=400)
    return style.status()
