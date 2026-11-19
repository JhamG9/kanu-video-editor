"""Servidor local del editor. Uso: python3 editor/server.py  →  http://localhost:8765"""
import json
import mimetypes
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import grade
import media
import project
import stab
import style

STATIC = Path(__file__).resolve().parent / "static"
PORT = 8765
exporter = project.Exporter(workers=2)
runner = project.BatchRunner(exporter)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200, cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, f, ctype):
        """Envía un archivo con soporte de Range (el <video> del navegador lo necesita para avanzar)."""
        size = f.stat().st_size
        rng = self.headers.get("Range")
        a, b = 0, size - 1
        if rng and rng.startswith("bytes="):
            s, _, e = rng[6:].partition("-")
            if s:
                a, b = int(s), (int(e) if e else size - 1)
            else:
                a = max(0, size - int(e))
            b = min(b, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(a)
            left = b - a + 1
            try:
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self._send((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path.startswith("/static/"):
                f = (STATIC / u.path[8:]).resolve()
                if f.parent != STATIC or not f.exists():
                    return self._send({"error": "no existe"}, code=404)
                return self._send(f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            if u.path == "/api/clips":
                return self._send({"clips": [project.clip_info(n) for n in project.clips()],
                                   "presets": {k: v["label"] for k, v in media.PRESETS.items()},
                                   "denoise": media.DENOISE_LABEL, "stab_levels": stab.LABELS,
                                   "stab_methods": stab.METHODS, "stab_available": stab.available()})
            if u.path == "/api/style":
                return self._send(style.status())
            if u.path == "/api/batch":
                return self._send({"state": runner.state, "options": project.BATCH_OPTIONS,
                                   "batches": project.batches()[:20]})
            if u.path == "/api/clip":
                return self._send(project.clip_info(q["clip"]))
            if u.path == "/api/frame":
                return self._frame(q["clip"], float(q.get("t", 0)), int(q.get("w", 1920)), q.get("orig") == "1")
            if u.path == "/api/crop":
                p, m = project.preview_source(q["clip"])[0], project.meta(q["clip"])
                img = media.crop_png(p, float(q["t"]), float(q["cx"]), float(q["cy"]), m, q.get("dn", "off"))
                return self._send(img, "image/png")
            if u.path == "/api/proxy":
                return self._send_file(project.proxy_file(q["clip"]), "video/mp4")
            if u.path == "/api/compare":
                f = project.compare_file(q["clip"])
                if not f:
                    return self._send({"error": "todavía no hay comparación"}, code=404)
                return self._send_file(f, "video/mp4")
            if u.path == "/api/jobs":
                return self._send(exporter.list())
            if u.path == "/api/cache":
                return self._send({"bytes": project.cache_size()})
            return self._send({"error": "no existe"}, code=404)
        except FileNotFoundError as e:
            return self._send({"error": f"no encontrado: {e}"}, code=404)
        except subprocess.CalledProcessError as e:
            return self._send({"error": e.stderr.decode(errors="ignore")[-500:]}, code=500)

    def _frame(self, clip, t, w, orig=False):
        m = project.meta(clip)
        t = round(min(max(t, 0), m["duration"] - 0.05), 2)
        src, _ = project.preview_source(clip) if w > 400 and not orig else (project.clip_path(clip), None)
        fm = m
        if w > 400 and not orig:                       # con reducción de ruido: el fotograma sale de su copia
            dn = project.denoised_proxy_ready(clip)
            if dn:
                src, fm = dn, {}                       # la copia ya tiene los superblancos tratados
            elif media.DENOISE.get(project.load(clip).get("denoise", "off")):
                project.prepare_proxy(clip)
        f = project.CACHE / "frames" / f"{src.stem}_v2_{w}_{t:.2f}.jpg"
        if not f.exists():
            f.write_bytes(media.frame_jpeg(src, t, fm, w))
        return self._send(f.read_bytes(), "image/jpeg", cache=True)

    def do_PUT(self):
        """Subida de un video a Videos/ (el navegador envía el archivo tal cual, sin cargarlo en memoria)."""
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path != "/api/upload":
                return self._send({"error": "no existe"}, code=404)
            n = int(self.headers.get("Content-Length") or 0)
            where = q.get("dest", "videos")
            if where == "estilo_lut":                     # LUT propia: siempre estilo/lut.cube
                if not q["name"].lower().endswith(".cube"):
                    raise ValueError("La LUT debe ser un archivo .cube")
                name, folder = "lut.cube", style.DIR
            else:
                name = project.safe_video_name(q["name"])
                folder = {"videos": project.VIDEOS, "estilo_original": style.ORIG, "estilo_editado": style.EDIT}[where]
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / name
            if where != "videos" and dest.exists():       # en el estilo, subir de nuevo reemplaza
                dest.unlink()
            if dest.exists() and dest.stat().st_size == n:
                self._discard(n)  # ya está: no se sube dos veces
                return self._send({"name": name, "skipped": True})
            if dest.exists():
                stem, ext = dest.stem, dest.suffix
                i = 2
                while (folder / f"{stem}_{i}{ext}").exists():
                    i += 1
                name = f"{stem}_{i}{ext}"
                dest = folder / name
            tmp = dest.with_name(dest.name + ".parcial")
            left = n
            with open(tmp, "wb") as fh:
                while left > 0:
                    chunk = self.rfile.read(min(4 << 20, left))
                    if not chunk:
                        break
                    fh.write(chunk)
                    left -= len(chunk)
            if left:
                tmp.unlink(missing_ok=True)
                return self._send({"error": "la subida se cortó"}, code=400)
            tmp.replace(dest)
            return self._send({"name": name, "skipped": False})
        except Exception as e:  # noqa
            return self._send({"error": str(e)}, code=500)

    def _discard(self, n):
        while n > 0:
            n -= len(self.rfile.read(min(4 << 20, n)) or b"x" * n)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/lut":
                return self._send(grade.lut_bytes(self._body()), "application/octet-stream")
            if u.path == "/api/settings":
                project.save(q["clip"], self._body())
                return self._send(project.clip_info(q["clip"]))
            if u.path == "/api/auto":
                project.auto(q["clip"])
                return self._send(project.clip_info(q["clip"]))
            if u.path == "/api/proxy/prepare":
                project.prepare_proxy(q["clip"])
                return self._send({"ok": True})
            if u.path == "/api/straighten":
                s, msg = project.straighten(q["clip"])
                project.save(q["clip"], s)
                info = project.clip_info(q["clip"])
                info["message"] = msg
                return self._send(info)
            if u.path == "/api/stabilize":
                project.prepare_stab(q["clip"])
                return self._send(project.clip_info(q["clip"]))
            if u.path == "/api/export":
                b = self._body()
                ids = exporter.add(b["clips"], b["presets"], b.get("audio", False), b.get("upload", False))
                return self._send({"added": len(ids)})
            if u.path == "/api/batch":
                b = self._body()
                names = [project.safe_video_name(n) for n in b["clips"]]
                for n in names:
                    project.clip_path(n)  # que existan
                return self._send(runner.start(names, b.get("options", {}), b.get("note", ""), b.get("title", ""),
                                               b.get("process", True)))
            if u.path == "/api/spot/measure":
                sp = media.measure_spot(project.clip_path(q["clip"]), project.meta(q["clip"]),
                                        float(q["x"]), float(q["y"]), float(q.get("r", 40)))
                if not sp:
                    return self._send({"error": "Ahí no encontré una mancha de sensor. Haz clic justo encima."}, code=404)
                return self._send(sp)
            if u.path == "/api/spot/prepare":
                project.prepare_clean(q["clip"])
                return self._send(project.clip_info(q["clip"]))
            if u.path == "/api/style/learn":
                style.learn()
                return self._send(style.status())
            if u.path == "/api/style/config":
                style.set_config(**self._body())
                return self._send(style.status())
            if u.path == "/api/style/delete":           # todo solo si se pide explícitamente
                if q.get("all") == "1":
                    style.delete(None)
                elif q.get("name"):
                    style.delete(q["name"])
                else:
                    return self._send({"error": "falta qué borrar"}, code=400)
                return self._send(style.status())
            if u.path == "/api/jobs/clear":
                exporter.clear_done()
                return self._send({"ok": True})
            if u.path == "/api/jobs/cancel":
                exporter.cancel_all()
                return self._send({"ok": True})
            if u.path == "/api/cache/clean":
                if any(j["status"] in ("procesando", "estabilizando") for j in exporter.list()):
                    return self._send({"error": "Espera a que termine la exportación"}, code=409)
                return self._send({"freed": project.clean_cache()})
            if u.path == "/api/open-exports":
                subprocess.run(["open", str(project.SUBIR if project.SUBIR.exists() else project.EXPORT)])
                return self._send({"ok": True})
            return self._send({"error": "no existe"}, code=404)
        except FileNotFoundError as e:
            return self._send({"error": f"no encontrado: {e}"}, code=404)
        except Exception as e:  # noqa
            return self._send({"error": str(e)}, code=500)


def main():
    style.load_lut()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Editor listo en {url}  (Ctrl+C para cerrar)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
