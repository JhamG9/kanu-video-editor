"""Aplicación FastAPI de Kanu: la API del editor y, mientras llega la nueva interfaz, la interfaz actual."""
import subprocess

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from kanu import __version__, config
from kanu.core import style

from .routes import batches, clips, export, home, media, spots
from .routes import style as style_routes

UI = config.ROOT / "apps" / "legacy-ui"


def create_app() -> FastAPI:
    app = FastAPI(title="Kanu", version=__version__,
                  description="Motor de Kanu: corrección de color, estabilización, manchas, cortes y exportación.")

    # la interfaz espera {"error": "..."} en cualquier fallo
    @app.exception_handler(FileNotFoundError)
    async def not_found(_: Request, e: FileNotFoundError):
        return JSONResponse({"error": f"no encontrado: {e}"}, status_code=404)

    @app.exception_handler(subprocess.CalledProcessError)
    async def tool_failed(_: Request, e: subprocess.CalledProcessError):
        err = e.stderr.decode(errors="ignore") if isinstance(e.stderr, bytes) else str(e.stderr or e)
        return JSONResponse({"error": err[-500:]}, status_code=500)

    @app.exception_handler(Exception)
    async def failed(_: Request, e: Exception):
        return JSONResponse({"error": str(e)}, status_code=500)

    for r in (clips, media, spots, export, batches, home, style_routes):
        app.include_router(r.router)

    @app.get("/api/health", tags=["sistema"])
    def health():
        return {"ok": True, "version": __version__}

    if UI.exists():
        app.mount("/static", StaticFiles(directory=UI), name="ui")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(UI / "index.html", headers={"Cache-Control": "no-store"})

    style.load_lut()
    return app


app = create_app()
