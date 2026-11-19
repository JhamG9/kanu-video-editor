"""Proyecto: carpetas, ajustes por clip (JSON) y cola de exportación.

Los ajustes viven en ajustes/<clip>.json. Claude los escribe (corrección automática)
y el editor los lee y modifica: es el mismo archivo para los dos.
"""
import hashlib
import json
import threading
import time
import subprocess
from pathlib import Path

import grade
import media
import stab
import style

ROOT = Path(__file__).resolve().parent.parent
VIDEOS = ROOT / "Videos"
AJUSTES = ROOT / "ajustes"
CACHE = ROOT / ".cache"
SUBIR = ROOT / "videos subir"  # finales listos para subir a los bancos de stock
TANDAS = ROOT / "tandas"       # una ficha .json por tanda: opciones y nota
EXPORT = ROOT / "Exportados"
for d in (AJUSTES, CACHE / "frames", CACHE / "luts", EXPORT):
    d.mkdir(parents=True, exist_ok=True)

VIDEO_EXT = {".mp4", ".mov", ".mxf", ".m4v"}
_meta_lock = threading.Lock()


def clips():
    return sorted(p.name for p in VIDEOS.iterdir() if p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."))


def clip_path(name):
    p = (VIDEOS / name).resolve()
    if p.parent != VIDEOS.resolve() or not p.exists():
        raise FileNotFoundError(name)
    return p


def meta(name):
    f = CACHE / "meta.json"
    with _meta_lock:
        data = json.loads(f.read_text()) if f.exists() else {}
        p = clip_path(name)
        key = f"{name}:{p.stat().st_size}:v2"
        if key not in data:
            data[key] = media.probe(p)
            f.write_text(json.dumps(data, indent=1))
        return data[key]


def recorded(name):
    """Fecha de grabación (AAAA-MM-DD) que guarda la cámara en el archivo; si no la hay, la del archivo."""
    f = CACHE / "meta.json"
    p = clip_path(name)
    key = f"{name}:{p.stat().st_size}:rec"
    with _meta_lock:
        data = json.loads(f.read_text()) if f.exists() else {}
        if key not in data:
            out = subprocess.run([media.FFPROBE, "-v", "error", "-show_entries", "format_tags=creation_time",
                                  "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
            data[key] = out[:10] if len(out) >= 10 and out[:4].isdigit() else time.strftime(
                "%Y-%m-%d", time.localtime(p.stat().st_mtime))
            f.write_text(json.dumps(data, indent=1))
        return data[key]


MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha(d):
    y, m, dd = d[:10].split("-")
    return f"{int(dd)} {MESES[int(m) - 1]} {y}"


def clip_group(name, s):
    """Caja de la lista: la tanda con que se subió o, si no, el día de grabación."""
    tid = (s.get("batch") or {}).get("tanda")
    b = batch_index().get(tid) if tid else None
    rec = recorded(name)
    if b:
        return {"id": "t:" + tid, "title": b["title"], "sub": f"Subida el {fecha(b['date'])}", "sort": b["id"]}
    return {"id": "d:" + rec, "title": f"Grabados el {fecha(rec)}", "sub": "", "sort": rec}


SEGMENT_DEFAULT = {"enabled": True, "min": 12, "max": 14, "max_slow": 1.2}


def default_settings():
    s = dict(grade.DEFAULTS)
    s.update({"rotate": 0.0, "denoise": "off", "stabilize": "off", "stab_method": "auto", "trim_in": 0.0, "trim_out": None, "sections": [],
              "segment": dict(SEGMENT_DEFAULT), "status": "pendiente", "auto": None, "batch": None, "spots": []})
    return s


def load(name):
    f = AJUSTES / (Path(name).stem + ".json")
    s = default_settings()
    if f.exists():
        s.update(json.loads(f.read_text()))
    if s["stabilize"] not in stab.LEVELS:
        s["stabilize"] = "off"
    seg = dict(SEGMENT_DEFAULT)
    seg.update({k: v for k, v in (s.get("segment") or {}).items() if k in SEGMENT_DEFAULT})
    s["segment"] = seg
    return s


def save(name, s):
    clean = default_settings()
    clean.update({k: v for k, v in s.items() if k in clean})
    (AJUSTES / (Path(name).stem + ".json")).write_text(json.dumps(clean, indent=2, ensure_ascii=False))
    return clean


TILT_MIN_CONF = 0.15


def straighten(name, s=None):
    """Mide la inclinación y la aplica si hay líneas rectas fiables. Devuelve (ajustes, mensaje)."""
    s = s or load(name)
    ang, conf, n = media.detect_tilt(clip_path(name), meta(name))
    if conf < TILT_MIN_CONF:
        return s, "No encontré líneas rectas fiables (paisaje natural): lo dejo como está."
    if abs(ang) < 0.3:
        s["rotate"] = 0.0
        return s, "Ya está derecho."
    s["rotate"] = ang
    return s, f"Enderezado {ang:+.1f}° (confianza {round(conf * 100)} %)."


def auto(name, keep_status=False):
    """Corrección automática de un clip (la hace Claude, sin intervención)."""
    p, m = clip_path(name), meta(name)
    col, lvl, sigma, why, stats, stab_level = media.analyze(p, m)
    # tu estilo: si lo enseñaste, los colores salen de cómo editaste tus videos más parecidos
    try:
        st_pred = style.predict(style._frames(p, m, [m["duration"] * f for f in (0.15, 0.35, 0.5, 0.65, 0.85)]), col)
    except Exception:  # noqa
        st_pred = None
    if st_pred:
        params, near = st_pred
        col.update(params)
        why = [w for w in why if "vibración" in w or "superblancos" in w] + \
              [f"tu estilo: como editaste {', '.join(n[-12:] for n in near[:3])}"]
    s = load(name)
    s.update(col)
    s["denoise"] = lvl
    s["stabilize"] = stab_level
    s, msg = straighten(name, s)
    if abs(s.get("rotate") or 0) >= 0.3:
        why = list(why) + [msg]
    why = list(why) + apply_batch(s)
    s["auto"] = {"why": why, "stats": stats, "noise": sigma, "noise_level": lvl, "date": time.strftime("%Y-%m-%d %H:%M")}
    if not keep_status or s["status"] == "pendiente":
        s["status"] = "auto"
    return save(name, s)


def cut_plan(m, s):
    """Clips que salen al exportar. Con tramos (cortador) cada tramo activo sale por separado y,
    si es largo, se divide en clips de stock con la misma regla de siempre."""
    d = m["duration"]
    ti, to = s["trim_in"] or 0.0, min(s["trim_out"] or d, d)
    secs = s.get("sections") or [[0.0, d, True]]
    out = []
    for i, (a, b, on) in enumerate(secs):
        a, b = max(a, ti), min(b, to)
        if not on or b - a < 0.5:
            continue
        p = media.plan(d, m["fps_raw"], a, b, s["segment"])
        for x, y in p["segments"]:
            out.append({"a": x, "b": y, "speed": p["speed"], "fps_raw": p["fps_raw"], "section": i + 1,
                        "len": round((y - x) * p["speed"], 2), "short": p["short"]})
    return out


def clip_info(name):
    m = meta(name)
    s = load(name)
    segs = cut_plan(m, s)
    first = segs[0] if segs else {"speed": 1.0, "fps_raw": m["fps_raw"], "len": 0.0}
    pl = {"segments": [(g["a"], g["b"]) for g in segs], "speed": max([g["speed"] for g in segs] or [1.0]),
          "fps_raw": first["fps_raw"], "clip_len": first["len"], "short": any(g["short"] for g in segs)}
    src, used = preview_source(name, s)
    st = dict(STAB_STATE.get(name, {}))
    cs = CLEAN_STATE.get(name) or {}
    cp = clean_path(name, s)
    st["clean"] = {"running": bool(cs.get("running")), "error": cs.get("error"), "ready": bool(cp and cp.exists())}
    st.update(ready=used is not None or s["stabilize"] == "off", method_used=used,
              compare=used is not None and compare_path(src).exists(), proxy_stab=stab_proxy(name, s))
    dn = denoised_proxy_ready(name, s)
    return {"name": name, "meta": m, "settings": s, "src_id": src.stem + (f"|{dn.stem}" if dn else ""),
            "denoise_preview": bool(dn) if media.DENOISE.get(s.get("denoise", "off")) else None,
            "segments": [[round(a, 3), round(b, 3)] for a, b in pl["segments"]],
            "plan": {"speed": pl["speed"], "fps_raw": pl["fps_raw"], "fps": round(media._fps(pl["fps_raw"]), 3),
                     "clip_len": round(pl["clip_len"], 2), "short": pl["short"]},
            "stab": st, "group": clip_group(name, s), "recorded": recorded(name), "cuts": [{k: g[k] for k in ("section", "len", "speed")} | {"fps": round(media._fps(g["fps_raw"]), 3)}
                                 for g in segs]}


# ---------------------------------------------------------------- caché
def cache_size():
    return sum(f.stat().st_size for f in CACHE.rglob("*") if f.is_file())


def clean_cache():
    """Borra intermedios estabilizados y fotogramas (se regeneran solos si hacen falta)."""
    busy = any(st.get("running") for st in STAB_STATE.values())
    freed = 0
    for d in (CACHE / "estab", CACHE / "frames", CACHE / "proxy", CACHE / "limpio"):
        for f in d.glob("*"):
            if f.is_file() and not (busy and "parcial" in f.name):
                freed += f.stat().st_size
                f.unlink()
    return freed


# ---------------------------------------------------------------- estabilización
STAB_STATE = {}  # nombre -> {"running", "progress", "stage", "error"}


# ---------------------------------------------------------------- manchas del sensor
CLEAN_STATE = {}  # nombre -> {"running", "error"}


def spots_key(s):
    sp = s.get("spots") or []
    return hashlib.md5(json.dumps(sp, sort_keys=True).encode()).hexdigest()[:8] if sp else ""


def clean_path(name, s=None):
    s = s or load(name)
    k = spots_key(s)
    return CACHE / "limpio" / f"{Path(name).stem}_{k}.mov" if k else None


def ensure_clean(name, s=None):
    """Video original sin las manchas (ProRes). Se hace una vez por juego de manchas."""
    s = s or load(name)
    out = clean_path(name, s)
    if out is None:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    with _proxy_guard:
        lk = _proxy_locks.setdefault(str(out), threading.Lock())
    with lk:
        if not out.exists():
            media.clean_video(clip_path(name), meta(name), s["spots"], out.with_suffix(""), out)
    return out


def prepare_clean(name):
    """En segundo plano, para que el visor muestre el clip sin manchas cuanto antes."""
    s = load(name)
    if not s.get("spots") or (CLEAN_STATE.get(name) or {}).get("running"):
        return
    CLEAN_STATE[name] = {"running": True, "error": None}

    def work():
        try:
            ensure_clean(name, s)
        except Exception as e:  # noqa
            CLEAN_STATE[name]["error"] = str(e)[-400:]
        CLEAN_STATE[name]["running"] = False
    threading.Thread(target=work, daemon=True).start()


def base_source(name, s=None):
    """Original, o su versión sin manchas si ya está hecha."""
    s = s or load(name)
    c = clean_path(name, s)
    return c if c and c.exists() else clip_path(name)


def preview_source(name, s=None):
    """Archivo a mostrar en el visor: el estabilizado si ya existe, si no el original (limpio de manchas si lo hay)."""
    s = s or load(name)
    src = base_source(name, s)
    if s["stabilize"] == "off":
        return src, None
    for mth in _stab_methods(s):
        p = stab.out_path(CACHE, name, s["stabilize"], mth, spots_key(s))
        if p.exists():
            return p, mth
    return src, None


_proxy_locks = {}
_proxy_guard = threading.Lock()


def _stab_methods(s):
    return [s["stab_method"]] if s["stab_method"] != "auto" else ["giroscopio", "imagen"]


def stab_proxy_path(name, method, s=None):
    s = s or load(name)
    return CACHE / "proxy" / (stab.out_path(CACHE, name, s["stabilize"], method, spots_key(s)).stem + ".mp4")


def stab_proxy(name, s=None):
    """Copia ligera ya estabilizada (sobrevive aunque se borre el intermedio de ~3.5 GB). Devuelve el método o None."""
    s = s or load(name)
    if s["stabilize"] == "off":
        return None
    return next((m for m in _stab_methods(s) if stab_proxy_path(name, m, s).exists()), None)


def build_stab_proxy(name, s=None):
    """Crea la copia de reproducción estabilizada a partir del intermedio (si existe)."""
    s = s or load(name)
    src, used = preview_source(name, s)
    if used is None:
        return None
    out = stab_proxy_path(name, used, s)
    out.parent.mkdir(parents=True, exist_ok=True)
    with _proxy_guard:
        lk = _proxy_locks.setdefault(str(out), threading.Lock())
    with lk:
        if not out.exists():
            media.proxy_video(src, meta(name), out)
    return out


def proxy_file(name, build=True):
    """Copia para reproducir en el visor, con la reducción de ruido aplicada si el clip la lleva."""
    s = load(name)
    base = _proxy_base(name, s, build)
    lvl = s.get("denoise", "off")
    if base is None or not media.DENOISE.get(lvl):
        return base
    out = base.with_name(f"{base.stem}_dn{lvl}.mp4")
    if out.exists() or not build:
        return out if out.exists() else None
    with _proxy_guard:
        lk = _proxy_locks.setdefault(str(out), threading.Lock())
    with lk:
        if not out.exists():
            media.denoise_proxy(base, out, lvl)
    return out


def denoised_proxy_ready(name, s=None):
    s = s or load(name)
    if not media.DENOISE.get(s.get("denoise", "off")):
        return None
    p = proxy_file(name, build=False)
    return p if p and "_dn" in p.stem else None


def _proxy_base(name, s, build=True):
    """Copia de reproducción sin reducción de ruido: la estabilizada si existe, si no la del original."""
    m = stab_proxy(name, s)
    if m:
        return stab_proxy_path(name, m, s)
    src, used = preview_source(name, s)
    if used is not None:
        return build_stab_proxy(name, s) if build else (stab_proxy_path(name, used, s) if stab_proxy_path(name, used, s).exists() else None)
    h = hashlib.md5(f"{src.name}|{src.stat().st_size}|v1".encode()).hexdigest()[:8]
    out = CACHE / "proxy" / f"{src.stem}_{h}.mp4"
    if out.exists() or not build:
        return out if out.exists() else None
    out.parent.mkdir(parents=True, exist_ok=True)
    with _proxy_guard:
        lk = _proxy_locks.setdefault(str(out), threading.Lock())
    with lk:
        if not out.exists():
            media.proxy_video(src, meta(name), out)
    return out


def prepare_proxy(name):
    threading.Thread(target=lambda: proxy_file(name), daemon=True).start()


def compare_path(stab_out):
    return Path(stab_out).with_name(Path(stab_out).stem + "_comparar.mp4")


def compare_file(name):
    """Video antes/después de la estabilización, si ya está hecho."""
    src, used = preview_source(name)
    if used is None:
        return None
    p = compare_path(src)
    return p if p.exists() else None


def prepare_stab(name):
    """Genera en segundo plano el intermedio estabilizado para verlo en el editor."""
    st = STAB_STATE.get(name)
    if st and st.get("running"):
        return
    s = load(name)
    STAB_STATE[name] = {"running": True, "progress": 0.0, "stage": "iniciando", "error": None}

    def work():
        state = STAB_STATE[name]
        try:
            def prog(p, stage):
                state.update(progress=p, stage=stage)
            clean = None
            if s.get("spots"):
                state.update(stage="quitando manchas")
                clean = ensure_clean(name, s)
            out, _ = stab.ensure(clip_path(name), name, s["stabilize"], s["stab_method"], CACHE, prog,
                                 clean=clean, key=spots_key(s))
            cmp = compare_path(out)
            if not cmp.exists():
                state.update(progress=0.999, stage="armando comparación")
                media.compare_video(clip_path(name), out, meta(name), cmp)
            state.update(progress=0.999, stage="preparando reproducción")
            build_stab_proxy(name, s)
        except Exception as e:  # noqa
            state["error"] = str(e)[-500:]
        state["running"] = False

    threading.Thread(target=work, daemon=True).start()


def cube_for(settings):
    col = grade.color_settings(settings)
    lut_key = str(style.LUT.stat().st_mtime) if grade.STYLE_LUT is not None and style.LUT.exists() else ""
    h = hashlib.md5((json.dumps(col, sort_keys=True) + lut_key).encode()).hexdigest()[:12]
    path = CACHE / "luts" / f"{h}.cube"
    if not path.exists():
        grade.write_cube(col, path)
    return path


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
                info = clip_info(name)
                s, m = info["settings"], info["meta"]
                segs = info["segments"]
                plan = cut_plan(m, s)
                for pk in presets:
                    P = media.PRESETS[pk]
                    outdir = SUBIR if to_upload else EXPORT / pk
                    outdir.mkdir(parents=True, exist_ok=True)
                    for i, (a, b) in enumerate(segs):
                        suffix = f"_{i + 1:02d}" if len(segs) > 1 else ""
                        if to_upload and len(presets) > 1:  # varios formatos en la misma carpeta
                            suffix += f"_{pk}"
                        out = outdir / f"{Path(name).stem}{suffix}.{P['ext']}"
                        job = {"id": f"{time.time():.6f}-{len(self.jobs)}", "clip": name, "preset": pk,
                               "label": P["label"], "segment": i + 1, "of": len(segs), "a": a, "b": b,
                               "speed": plan[i]["speed"], "fps_raw": plan[i]["fps_raw"],
                               "out": str(out.relative_to(ROOT)), "status": "en cola", "progress": 0.0,
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
            src = clip_path(job["clip"])
            clean = None
            if job["settings"].get("spots"):
                job.update(status="estabilizando", stage="quitando manchas")
                clean = ensure_clean(job["clip"], job["settings"])
            if job["settings"].get("stabilize", "off") != "off":
                job["status"] = "estabilizando"

                def prog(p, stage):
                    job.update(progress=p, stage=stage)
                src, used = stab.ensure(src, job["clip"], job["settings"]["stabilize"],
                                        job["settings"].get("stab_method", "auto"), CACHE, prog,
                                        clean=clean, key=spots_key(job["settings"]))
                job.update(status="procesando", progress=0.0, stage=None, stab_method=used)
            elif clean:
                src = clean
                job.update(status="procesando", progress=0.0, stage=None)
            out = ROOT / job["out"]
            tmp = out.with_name(out.stem + ".parcial" + out.suffix)
            cube = cube_for(job["settings"])
            cmd = media.export_cmd(src, tmp, job["a"], job["b"], job["preset"], cube, job["settings"], job["meta"],
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


# ------------------------------------------------------------------ tandas (subir videos + indicaciones)
BATCH_OPTIONS = {
    "estable": "Ya viene estable (trípode, dron o gimbal)",
    "calido": "Conservar colores cálidos (amanecer o atardecer)",
    "sin_ralentizar": "Sin ralentizar",
}


def apply_batch(s):
    """Aplica las opciones de la tanda sobre la corrección automática. Devuelve las razones."""
    b = s.get("batch") or {}
    why = []
    if b.get("estable") and s["stabilize"] != "off":
        s["stabilize"] = "off"
        why.append("tanda: ya viene estable → sin estabilizar")
    if b.get("calido") and (s.get("temperature") or 0) < 0:
        s["temperature"] = 0
        why.append("tanda: conservo los colores cálidos")
    if b.get("sin_ralentizar"):
        s["segment"]["max_slow"] = 1
    if b.get("min") and b.get("max"):
        s["segment"]["min"], s["segment"]["max"] = float(b["min"]), float(b["max"])
    if b.get("nota"):
        why.append("nota de la tanda: " + b["nota"][:200])
    return why


def safe_video_name(name):
    n = Path(name).name.strip()
    if not n or n.startswith(".") or Path(n).suffix.lower() not in VIDEO_EXT:
        raise ValueError(f"No es un video: {name}")
    return n


def finish_clip(name):
    """Tras exportar: deja una copia ligera estabilizada para el visor y borra el intermedio grande."""
    try:
        build_stab_proxy(name)
    except Exception:  # noqa
        pass
    for f in (CACHE / "estab").glob(Path(name).stem + "_*"):
        if "parcial" not in f.name:
            f.unlink(missing_ok=True)


class BatchRunner:
    """Procesa una tanda completa (como `cli.py stock`) dentro del editor."""

    def __init__(self, exporter):
        self.ex = exporter
        self.state = {"running": False}
        self.lock = threading.Lock()

    def start(self, names, options, note, title, process=True):
        with self.lock:
            if process and self.state.get("running"):
                raise RuntimeError("Ya hay una tanda procesándose")
            info = register_batch(names, options, note, title)
            if not process:
                return info
            self.state = {"running": True, "id": info["id"], "title": info["title"], "stage": "analizando",
                          "done": 0, "total": len(names)}
        threading.Thread(target=self._run, args=(names, info), daemon=True).start()
        return info

    def _run(self, names, info):
        st = self.state
        try:
            for i, n in enumerate(names):
                st.update(stage=f"corrigiendo {n}", done=i)
                s = load(n)
                if s["status"] not in ("manual", "aprobado"):
                    auto(n)
            st.update(stage="exportando", done=0)
            ids = set(self.ex.add(names, ["4k_h264"], keep_audio=False, to_upload=True))
            cleaned = set()
            while True:
                jobs = [j for j in self.ex.list() if j["id"] in ids]
                pend = [j for j in jobs if j["status"] in ("en cola", "procesando", "estabilizando")]
                for c in {j["clip"] for j in jobs} - {j["clip"] for j in pend} - cleaned:
                    finish_clip(c)
                    cleaned.add(c)
                st.update(done=len(jobs) - len(pend), total=len(jobs),
                          errors=sum(j["status"] not in ("listo", "en cola", "procesando", "estabilizando") for j in jobs))
                if not pend:
                    break
                time.sleep(2)
            st.update(stage="listo")
        except Exception as e:  # noqa
            st.update(stage="error", error=str(e)[-400:])
        st["running"] = False


def register_batch(names, options, note, title):
    """Guarda la ficha de la tanda y la anota en cada clip (sin procesar nada)."""
    TANDAS.mkdir(exist_ok=True)
    tid = time.strftime("%Y-%m-%d_%H%M%S")
    hoy = time.strftime("%Y-%m-%d %H:%M")
    info = {"id": tid, "title": title or f"Subida del {fecha(hoy)}", "date": hoy, "clips": names,
            "options": {k: bool(options.get(k)) for k in BATCH_OPTIONS},
            "min": options.get("min"), "max": options.get("max"), "nota": note or ""}
    (TANDAS / f"{tid}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    batch = dict(info["options"], min=info["min"], max=info["max"], nota=info["nota"], tanda=tid)
    for n in names:
        s = load(n)
        s["batch"] = batch
        if b := batch.get("min"):
            s["segment"]["min"], s["segment"]["max"] = float(b), float(batch.get("max") or b + 2)
        if batch.get("sin_ralentizar"):
            s["segment"]["max_slow"] = 1
        save(n, s)
    return info


_bidx = {"mtime": None, "data": {}}


def batch_index():
    m = TANDAS.stat().st_mtime if TANDAS.exists() else None
    if m != _bidx["mtime"]:
        _bidx.update(mtime=m, data={b["id"]: b for b in batches()})
    return _bidx["data"]


def batches():
    if not TANDAS.exists():
        return []
    return sorted((json.loads(f.read_text()) for f in TANDAS.glob("*.json")), key=lambda b: b["id"], reverse=True)
