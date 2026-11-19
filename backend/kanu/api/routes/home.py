"""Pantalla de inicio: resumen de lo que hay (finales listos, último clip editado)."""
from pathlib import Path

from fastapi import APIRouter

from kanu import __version__, config
from kanu.services import library

router = APIRouter(prefix="/api", tags=["inicio"])


def _videos(folder: Path):
    if not folder.exists():
        return []
    return [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in config.VIDEO_EXT
            and ".parcial" not in p.name]


@router.get("/home")
def home():
    finals = sorted(_videos(config.SUBIR), key=lambda p: p.stat().st_mtime, reverse=True)
    names = set(library.clips())
    edited = [(f.stat().st_mtime, f.stem) for f in config.AJUSTES.glob("*.json")]
    last = next((n for _, stem in sorted(edited, reverse=True)
                 for n in names if Path(n).stem == stem), None)
    return {
        "version": __version__,
        "finals": {
            "count": len(finals),
            "bytes": sum(p.stat().st_size for p in finals),
            "latest": [{"name": p.name, "bytes": p.stat().st_size, "mtime": p.stat().st_mtime} for p in finals[:6]],
        },
        "last_edited": last,
    }
