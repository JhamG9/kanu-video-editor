"""Vistas previas: video sin manchas, intermedio estabilizado y copias de reproducción."""
import hashlib
import json
import threading
from pathlib import Path


from kanu import config
from kanu.core import grade
from kanu.core import spots
from kanu.core import style
from kanu.infra import ffmpeg as ff
from kanu.infra import gyroflow
from kanu.services import library


# ---------------------------------------------------------------- estabilización
STAB_STATE = {}  # nombre -> {"running", "progress", "stage", "error"}


# ---------------------------------------------------------------- manchas del sensor
CLEAN_STATE = {}  # nombre -> {"running", "error"}


def spots_key(s):
    sp = s.get("spots") or []
    return hashlib.md5(json.dumps(sp, sort_keys=True).encode()).hexdigest()[:8] if sp else ""


def clean_path(name, s=None):
    s = s or library.load(name)
    k = spots_key(s)
    return config.CACHE / "limpio" / f"{Path(name).stem}_{k}.mov" if k else None


def ensure_clean(name, s=None):
    """Video original sin las manchas (ProRes). Se hace una vez por juego de manchas."""
    s = s or library.load(name)
    out = clean_path(name, s)
    if out is None:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    with _proxy_guard:
        lk = _proxy_locks.setdefault(str(out), threading.Lock())
    with lk:
        if not out.exists():
            spots.clean_video(library.clip_path(name), library.meta(name), s["spots"], out.with_suffix(""), out)
    return out


def prepare_clean(name):
    """En segundo plano, para que el visor muestre el clip sin manchas cuanto antes."""
    s = library.load(name)
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
    s = s or library.load(name)
    c = clean_path(name, s)
    return c if c and c.exists() else library.clip_path(name)


def preview_source(name, s=None):
    """Archivo a mostrar en el visor: el estabilizado si ya existe, si no el original (limpio de manchas si lo hay)."""
    s = s or library.load(name)
    src = base_source(name, s)
    if s["stabilize"] == "off":
        return src, None
    for mth in _stab_methods(s):
        p = gyroflow.out_path(config.CACHE, name, s["stabilize"], mth, spots_key(s))
        if p.exists():
            return p, mth
    return src, None


_proxy_locks = {}


_proxy_guard = threading.Lock()


def _stab_methods(s):
    return [s["stab_method"]] if s["stab_method"] != "auto" else ["giroscopio", "imagen"]


def stab_proxy_path(name, method, s=None):
    s = s or library.load(name)
    return config.CACHE / "proxy" / (gyroflow.out_path(config.CACHE, name, s["stabilize"], method, spots_key(s)).stem + ".mp4")


def stab_proxy(name, s=None):
    """Copia ligera ya estabilizada (sobrevive aunque se borre el intermedio de ~3.5 GB). Devuelve el método o None."""
    s = s or library.load(name)
    if s["stabilize"] == "off":
        return None
    return next((m for m in _stab_methods(s) if stab_proxy_path(name, m, s).exists()), None)


def build_stab_proxy(name, s=None):
    """Crea la copia de reproducción estabilizada a partir del intermedio (si existe)."""
    s = s or library.load(name)
    src, used = preview_source(name, s)
    if used is None:
        return None
    out = stab_proxy_path(name, used, s)
    out.parent.mkdir(parents=True, exist_ok=True)
    with _proxy_guard:
        lk = _proxy_locks.setdefault(str(out), threading.Lock())
    with lk:
        if not out.exists():
            ff.proxy_video(src, library.meta(name), out)
    return out


def proxy_file(name, build=True):
    """Copia para reproducir en el visor, con la reducción de ruido aplicada si el clip la lleva."""
    s = library.load(name)
    base = _proxy_base(name, s, build)
    lvl = s.get("denoise", "off")
    if base is None or not ff.DENOISE.get(lvl):
        return base
    out = base.with_name(f"{base.stem}_dn{lvl}.mp4")
    if out.exists() or not build:
        return out if out.exists() else None
    with _proxy_guard:
        lk = _proxy_locks.setdefault(str(out), threading.Lock())
    with lk:
        if not out.exists():
            ff.denoise_proxy(base, out, lvl)
    return out


def denoised_proxy_ready(name, s=None):
    s = s or library.load(name)
    if not ff.DENOISE.get(s.get("denoise", "off")):
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
    out = config.CACHE / "proxy" / f"{src.stem}_{h}.mp4"
    if out.exists() or not build:
        return out if out.exists() else None
    out.parent.mkdir(parents=True, exist_ok=True)
    with _proxy_guard:
        lk = _proxy_locks.setdefault(str(out), threading.Lock())
    with lk:
        if not out.exists():
            ff.proxy_video(src, library.meta(name), out)
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
    s = library.load(name)
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
            out, _ = gyroflow.ensure(library.clip_path(name), name, s["stabilize"], s["stab_method"], config.CACHE, prog,
                                 clean=clean, key=spots_key(s))
            cmp = compare_path(out)
            if not cmp.exists():
                state.update(progress=0.999, stage="armando comparación")
                ff.compare_video(library.clip_path(name), out, library.meta(name), cmp)
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
    path = config.CACHE / "luts" / f"{h}.cube"
    if not path.exists():
        grade.write_cube(col, path)
    return path
