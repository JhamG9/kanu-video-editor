"""Estabilización con Gyroflow.

Dos modos:
- "giroscopio": usa los datos de movimiento que graba la cámara (Sony, GoPro, DJI de acción…).
  Es el más preciso y no se confunde con nubes, neblina o agua en movimiento.
- "imagen": analiza el movimiento en la propia imagen (flujo óptico), como el Warp Stabilizer
  de Premiere. Funciona con cualquier cámara (dron, celular…).
- "auto": giroscopio si el archivo lo trae; si no, imagen.

Se estabiliza el clip completo a un intermedio ProRes 10-bit (sin tocar el color) y después
el resto del proceso (ruido, color, cortes) trabaja sobre ese intermedio.
"""
import csv
import hashlib
import json
import re
import subprocess
import threading
from pathlib import Path

GYROFLOW = "/Applications/Gyroflow.app/Contents/MacOS/gyroflow"
FFMPEG = "/opt/homebrew/bin/ffmpeg"

LEVELS = {"off": None, "suave": 0.5, "media": 1.0, "fuerte": 1.5}
LABELS = {"off": "Apagada", "suave": "Suave", "media": "Media", "fuerte": "Fuerte"}
METHODS = {"auto": "Automático", "giroscopio": "Giroscopio de la cámara", "imagen": "Análisis de imagen (como Premiere)"}

_locks = {}
_guard = threading.Lock()
_gyro_cache = {}


def _lock(k):
    with _guard:
        return _locks.setdefault(k, threading.Lock())


def available():
    return Path(GYROFLOW).exists()


def _preset(level):
    return json.dumps({"version": 2, "stabilization": {
        "smoothing_params": [{"name": "smoothness", "value": LEVELS[level]}]}}).replace('"', "'")


def _estab_dir(cache):
    d = Path(cache) / "estab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def has_gyro(src, cache):
    """True si el archivo trae datos de giroscopio que Gyroflow entiende."""
    k = str(src)
    with _lock("gyro:" + k):  # dos exportaciones del mismo clip no deben comprobarlo a la vez
        if k in _gyro_cache:
            return _gyro_cache[k]
        tmp = _estab_dir(cache) / f"probe_{Path(src).stem}_{threading.get_ident()}.csv"
        subprocess.run([GYROFLOW, str(src), "-f", "--preset", _preset("media"), "--export-metadata", f"3:{tmp}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        ok = False
        if tmp.exists():
            rows = list(csv.DictReader(open(tmp)))
            ok = any(abs(float(r.get("org_gyro_x") or 0)) + abs(float(r.get("org_gyro_y") or 0)) > 0
                     for r in rows[:200])
            tmp.unlink()
        _gyro_cache[k] = ok
        return ok


def resolve_method(src, method, cache):
    if method == "imagen":
        return "imagen"
    if method == "giroscopio":
        return "giroscopio"
    return "giroscopio" if has_gyro(src, cache) else "imagen"


def out_path(cache, name, level, method, key=""):
    h = hashlib.md5(f"{name}|{level}|{method}|v3{('|' + key) if key else ''}".encode()).hexdigest()[:8]
    return _estab_dir(cache) / f"{Path(name).stem}_{method}_{level}_{h}.mov"


def _prores_source(src, cache):
    """Copia ProRes del original para el análisis de imagen (Gyroflow no decodifica H.264 4:2:2 10-bit por GPU)."""
    out = _estab_dir(cache) / f"{Path(src).stem}_fuente.mov"
    with _lock(str(out)):
        if not out.exists():
            tmp = out.with_name(out.stem + ".parcial.mov")
            subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
                            "-c:v", "prores_videotoolbox", "-profile:v", "hq", "-pix_fmt", "p210le",
                            "-c:a", "pcm_s16le", "-color_range", "tv", str(tmp)], check=True, capture_output=True)
            tmp.replace(out)
    return out


def _project_for(src, clean, level, tmp, workdir):
    """Proyecto de Gyroflow hecho con el ORIGINAL (giroscopio, lente, tiempo de lectura del sensor)
    pero que estabiliza el video ya limpio de manchas."""
    link = Path(workdir) / f"{Path(src).stem}_proyecto{Path(src).suffix}"
    link.unlink(missing_ok=True)
    link.symlink_to(Path(src).resolve())            # el proyecto se escribe junto al video: nunca en Videos/
    proj = link.with_suffix(".gyroflow")
    subprocess.run([GYROFLOW, str(link), "-f", "--export-project", "2"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=300)
    if not proj.exists():
        raise RuntimeError("Gyroflow no pudo preparar el proyecto")
    d = json.loads(proj.read_text())
    d["videofile"] = str(Path(clean).resolve())
    d.pop("videofile_bookmark", None)
    d["output"].update(codec="ProRes", codec_options="ProRes 422 HQ", pixel_format="P210LE", audio=True,
                       output_folder="file://" + str(Path(tmp).parent.resolve()) + "/", output_filename=Path(tmp).name)
    for p in d["stabilization"]["smoothing_params"]:
        if p["name"] == "smoothness":
            p["value"] = LEVELS[level]
    proj.write_text(json.dumps(d))
    return proj, link


def ensure(src, name, level, method, cache, on_progress=None, clean=None, key=""):
    """Devuelve (ruta del intermedio estabilizado, método usado). Lo genera si no existe.
    clean: video ya limpio de manchas (se estabiliza ese, con el giroscopio y el lente del original)."""
    if LEVELS.get(level) is None:
        return Path(clean or src), None
    method = resolve_method(src, method, cache)
    out = out_path(cache, name, level, method, key)
    with _lock(str(out)):  # varios formatos del mismo clip esperan al mismo intermedio
        if out.exists():
            return out, method
        report = on_progress or (lambda *_: None)
        inp, extra = Path(src), []
        tmp = out.with_name(out.stem + ".parcial.mov")
        cleanup = []
        if method == "imagen":
            report(0.0, "preparando copia para el análisis")
            inp = Path(clean) if clean else _prores_source(src, cache)   # el limpio ya es ProRes
            extra = ["--ignore-file-motion"]
        params = json.dumps({"codec": "ProRes", "codec_options": "ProRes 422 HQ", "pixel_format": "P210LE",
                             "audio": True, "audio_codec": "PCM (s16le)", "output_path": str(tmp)}).replace('"', "'")
        if clean and method == "giroscopio":
            proj, link = _project_for(src, clean, level, tmp, _estab_dir(cache))
            cleanup = [proj, link]
            cmd = [GYROFLOW, str(proj), "-f", "--no-gpu-decoding", "--stdout-progress"]
        else:
            cmd = [GYROFLOW, str(inp), "-f", "--no-gpu-decoding", "--stdout-progress", *extra,
                   "--preset", _preset(level), "-p", params]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        tail = []
        for line in p.stdout:
            tail = (tail + [line.strip()])[-15:]
            m = re.search(r"progress:.*?([\d.]+)%", line)
            if m:
                pct = float(m.group(1)) / 100
                stage = "analizando movimiento" if "Synchronization" in line else "estabilizando"
                report(min(pct, 0.999), stage)
        p.wait()
        for f in cleanup:
            f.unlink(missing_ok=True)
        if p.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise RuntimeError("Gyroflow falló:\n" + "\n".join(tail))
        tmp.replace(out)
        return out, method
