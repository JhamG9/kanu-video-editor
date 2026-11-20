"""Biblioteca de clips: ajustes por clip, información y corrección automática."""
import json
import subprocess
import threading
import time
from pathlib import Path


from kanu import config
from kanu.core import analysis
from kanu.core import grade
from kanu.core import segments as seg
from kanu.core import style
from kanu.infra import ffmpeg as ff
from kanu.infra import gyroflow
from kanu.services import batches
from kanu.services import previews


def clips():
    return sorted(p.name for p in config.VIDEOS.iterdir() if p.suffix.lower() in config.VIDEO_EXT and not p.name.startswith("."))


def clip_path(name):
    p = (config.VIDEOS / name).resolve()
    if p.parent != config.VIDEOS.resolve() or not p.exists():
        raise FileNotFoundError(name)
    return p


def meta(name):
    f = config.CACHE / "meta.json"
    with _meta_lock:
        data = json.loads(f.read_text()) if f.exists() else {}
        p = clip_path(name)
        key = f"{name}:{p.stat().st_size}:v2"
        if key not in data:
            data[key] = ff.probe(p)
            f.write_text(json.dumps(data, indent=1))
        return data[key]


_meta_lock = threading.Lock()


def recorded(name):
    """Fecha de grabación (AAAA-MM-DD) que guarda la cámara en el archivo; si no la hay, la del archivo."""
    f = config.CACHE / "meta.json"
    p = clip_path(name)
    key = f"{name}:{p.stat().st_size}:rec"
    with _meta_lock:
        data = json.loads(f.read_text()) if f.exists() else {}
        if key not in data:
            out = subprocess.run([config.FFPROBE, "-v", "error", "-show_entries", "format_tags=creation_time",
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
    b = batches.batch_index().get(tid) if tid else None
    rec = recorded(name)
    if b:
        return {"id": "t:" + tid, "title": b["title"], "sub": f"Subida el {fecha(b['date'])}", "sort": b["id"]}
    return {"id": "d:" + rec, "title": f"Grabados el {fecha(rec)}", "sub": "", "sort": rec}


SEGMENT_DEFAULT = {"enabled": True, "min": 12, "max": 14, "max_slow": 1.2}


def default_settings():
    s = dict(grade.DEFAULTS)
    s.update({"rotate": 0.0, "denoise": "off", "stabilize": "off", "stab_method": "auto", "trim_in": 0.0, "trim_out": None, "sections": [],
              "segment": dict(SEGMENT_DEFAULT), "status": "pendiente", "status_before": None, "auto": None, "batch": None, "spots": []})
    return s


def load(name):
    f = config.AJUSTES / (Path(name).stem + ".json")
    s = default_settings()
    if f.exists():
        s.update(json.loads(f.read_text()))
    if s["stabilize"] not in gyroflow.LEVELS:
        s["stabilize"] = "off"
    seg = dict(SEGMENT_DEFAULT)
    seg.update({k: v for k, v in (s.get("segment") or {}).items() if k in SEGMENT_DEFAULT})
    s["segment"] = seg
    return s


def save(name, s):
    clean = default_settings()
    clean.update({k: v for k, v in s.items() if k in clean})
    (config.AJUSTES / (Path(name).stem + ".json")).write_text(json.dumps(clean, indent=2, ensure_ascii=False))
    return clean


TILT_MIN_CONF = 0.15


def straighten(name, s=None):
    """Mide la inclinación y la aplica si hay líneas rectas fiables. Devuelve (ajustes, mensaje)."""
    s = s or load(name)
    ang, conf, n = analysis.detect_tilt(clip_path(name), meta(name))
    if conf < TILT_MIN_CONF:
        return s, "No encontré líneas rectas fiables (paisaje natural): lo dejo como está."
    if abs(ang) < 0.3:
        s["rotate"] = 0.0
        return s, "Ya está derecho."
    s["rotate"] = ang
    return s, f"Enderezado {ang:+.1f}° (confianza {round(conf * 100)} %)."


# Progreso de las correcciones automáticas en curso: {clip: {"stage", "t0", "stages"}} (lo lee la interfaz)
AUTO_STAGES = ["luz", "ruido", "vibracion", "estilo", "horizonte"]
AUTO_PROGRESS = {}


def auto(name, keep_status=False):
    """Corrección automática de un clip (la hace Claude, sin intervención)."""
    p, m = clip_path(name), meta(name)
    prog = AUTO_PROGRESS[name] = {"stage": "luz", "t0": time.time(), "duration": m["duration"]}
    try:
        return _auto(name, p, m, keep_status, lambda st: prog.update(stage=st))
    finally:
        AUTO_PROGRESS.pop(name, None)


def _auto(name, p, m, keep_status, step):
    col, lvl, sigma, why, stats, stab_level = analysis.analyze(p, m, step)
    step("estilo")
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
    step("horizonte")
    s, msg = straighten(name, s)
    if abs(s.get("rotate") or 0) >= 0.3:
        why = list(why) + [msg]
    why = list(why) + batches.apply_batch(s)
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
        p = seg.plan(d, m["fps_raw"], a, b, s["segment"])
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
    src, used = previews.preview_source(name, s)
    st = dict(previews.STAB_STATE.get(name, {}))
    cs = previews.CLEAN_STATE.get(name) or {}
    cp = previews.clean_path(name, s)
    st["clean"] = {"running": bool(cs.get("running")), "error": cs.get("error"), "ready": bool(cp and cp.exists())}
    st.update(ready=used is not None or s["stabilize"] == "off", method_used=used,
              compare=used is not None and previews.compare_path(src).exists(), proxy_stab=previews.stab_proxy(name, s))
    dn = previews.denoised_proxy_ready(name, s)
    return {"name": name, "meta": m, "settings": s, "src_id": src.stem + (f"|{dn.stem}" if dn else ""),
            "denoise_preview": bool(dn) if ff.DENOISE.get(s.get("denoise", "off")) else None,
            "segments": [[round(a, 3), round(b, 3)] for a, b in pl["segments"]],
            "plan": {"speed": pl["speed"], "fps_raw": pl["fps_raw"], "fps": round(seg._fps(pl["fps_raw"]), 3),
                     "clip_len": round(pl["clip_len"], 2), "short": pl["short"]},
            "stab": st, "group": clip_group(name, s), "recorded": recorded(name), "cuts": [{k: g[k] for k in ("section", "len", "speed")} | {"fps": round(seg._fps(g["fps_raw"]), 3)}
                                 for g in segs]}


# ---------------------------------------------------------------- caché
def cache_size():
    return sum(f.stat().st_size for f in config.CACHE.rglob("*") if f.is_file())


def clean_cache():
    """Borra intermedios estabilizados y fotogramas (se regeneran solos si hacen falta)."""
    busy = any(st.get("running") for st in previews.STAB_STATE.values())
    freed = 0
    for d in (config.CACHE / "estab", config.CACHE / "frames", config.CACHE / "proxy", config.CACHE / "limpio"):
        for f in d.glob("*"):
            if f.is_file() and not (busy and "parcial" in f.name):
                freed += f.stat().st_size
                f.unlink()
    return freed


def safe_video_name(name):
    n = Path(name).name.strip()
    if not n or n.startswith(".") or Path(n).suffix.lower() not in config.VIDEO_EXT:
        raise ValueError(f"No es un video: {name}")
    return n
