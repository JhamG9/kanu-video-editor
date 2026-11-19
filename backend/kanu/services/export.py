"""Cola de exportación."""
import subprocess
import threading
import time
from pathlib import Path


from kanu import config
from kanu.infra import ffmpeg as ff
from kanu.infra import gyroflow
from kanu.services import library
from kanu.services import previews


# ---------------------------------------------------------------- exportación
class Exporter:
    def __init__(self, workers=2):
        self.jobs = []
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.procs = {}
        for _ in range(workers):
            threading.Thread(target=self._worker, daemon=True).start()

    def add(self, names, presets, keep_audio=False, to_upload=False):
        added = []
        with self.cv:
            for name in names:
                info = library.clip_info(name)
                s, m = info["settings"], info["meta"]
                segs = info["segments"]
                plan = library.cut_plan(m, s)
                for pk in presets:
                    P = ff.PRESETS[pk]
                    outdir = config.SUBIR if to_upload else config.EXPORT / pk
                    outdir.mkdir(parents=True, exist_ok=True)
                    for i, (a, b) in enumerate(segs):
                        suffix = f"_{i + 1:02d}" if len(segs) > 1 else ""
                        if to_upload and len(presets) > 1:  # varios formatos en la misma carpeta
                            suffix += f"_{pk}"
                        out = outdir / f"{Path(name).stem}{suffix}.{P['ext']}"
                        job = {"id": f"{time.time():.6f}-{len(self.jobs)}", "clip": name, "preset": pk,
                               "label": P["label"], "segment": i + 1, "of": len(segs), "a": a, "b": b,
                               "speed": plan[i]["speed"], "fps_raw": plan[i]["fps_raw"],
                               "out": str(out.relative_to(config.DATA)), "status": "en cola", "progress": 0.0,
                               "error": None, "settings": dict(s), "meta": m, "audio": keep_audio}
                        self.jobs.append(job)
                        added.append(job["id"])
            self.cv.notify_all()
        return added

    def list(self):
        with self.lock:
            return [{k: v for k, v in j.items() if k not in ("settings", "meta")} for j in self.jobs]

    def clear_done(self):
        with self.lock:
            self.jobs = [j for j in self.jobs if j["status"] in ("en cola", "procesando", "estabilizando")]

    def cancel_all(self):
        with self.lock:
            for j in self.jobs:
                if j["status"] == "en cola":
                    j["status"] = "cancelado"
            for p in self.procs.values():
                p.terminate()

    def _worker(self):
        while True:
            with self.cv:
                job = next((j for j in self.jobs if j["status"] == "en cola"), None)
                while job is None:
                    self.cv.wait()
                    job = next((j for j in self.jobs if j["status"] == "en cola"), None)
                job["status"] = "procesando"
            self._run(job)

    def _run(self, job):
        try:
            src = library.clip_path(job["clip"])
            clean = None
            if job["settings"].get("spots"):
                job.update(status="estabilizando", stage="quitando manchas")
                clean = previews.ensure_clean(job["clip"], job["settings"])
            if job["settings"].get("stabilize", "off") != "off":
                job["status"] = "estabilizando"

                def prog(p, stage):
                    job.update(progress=p, stage=stage)
                src, used = gyroflow.ensure(src, job["clip"], job["settings"]["stabilize"],
                                        job["settings"].get("stab_method", "auto"), config.CACHE, prog,
                                        clean=clean, key=previews.spots_key(job["settings"]))
                job.update(status="procesando", progress=0.0, stage=None, stab_method=used)
            elif clean:
                src = clean
                job.update(status="procesando", progress=0.0, stage=None)
            out = config.DATA / job["out"]
            tmp = out.with_name(out.stem + ".parcial" + out.suffix)
            cube = previews.cube_for(job["settings"])
            cmd = ff.export_cmd(src, tmp, job["a"], job["b"], job["preset"], cube, job["settings"], job["meta"],
                                   job["audio"], job["speed"], job["fps_raw"])
            dur = (job["b"] - job["a"]) * job["speed"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.procs[job["id"]] = p
            t0 = time.time()
            for line in p.stdout:
                if line.startswith("out_time_us="):
                    try:
                        job["progress"] = min(0.999, int(line.split("=")[1]) / 1e6 / dur)
                        el = time.time() - t0
                        job["eta"] = round(el / max(job["progress"], 0.01) - el)
                    except ValueError:
                        pass
            err = p.stderr.read()
            p.wait()
            self.procs.pop(job["id"], None)
            if p.returncode != 0:
                tmp.unlink(missing_ok=True)
                job["status"] = "cancelado" if p.returncode < 0 else "error"
                job["error"] = err.strip()[-600:]
                return
            tmp.replace(out)
            job["progress"] = 1.0
            job["status"] = "listo"
            job["seconds"] = round(time.time() - t0, 1)
        except Exception as e:  # noqa
            job["status"] = "error"
            job["error"] = str(e)


def finish_clip(name):
    """Tras exportar: deja una copia ligera estabilizada para el visor y borra el intermedio grande."""
    try:
        previews.build_stab_proxy(name)
    except Exception:  # noqa
        pass
    for f in (config.CACHE / "estab").glob(Path(name).stem + "_*"):
        if "parcial" not in f.name:
            f.unlink(missing_ok=True)
