"""Mi estilo de color: Kanu aprende cómo editas tú a partir de pares original → editado.

Para cada par mide qué ajustes de Kanu (exposición, contraste, luces, sombras, blancos, negros,
temperatura, tinte, intensidad, saturación) convierten el original en tu versión. No hace falta
que los dos videos estén alineados ni con el mismo recorte: se comparan sus tonos y colores, no
los píxeles uno a uno. Con un video nuevo busca tus pares más parecidos (tipo de escena) y aplica
cómo los editaste.

Carpetas (en la raíz del proyecto):
    estilo/original/   videos sin editar
    estilo/editado/    tu versión, con el mismo nombre (la extensión puede cambiar)
    estilo/lut.cube    opcional: tu LUT o preset exportado como .cube
    estilo/modelo.json lo aprendido
    estilo/config.json {"enabled": true, "lut": false}
"""
import json
import threading
import time
from pathlib import Path

import numpy as np
from kanu import config as cfg
from kanu.core import grade
from kanu.infra import ffmpeg as ff
from kanu.services import library


DIR = cfg.ESTILO
ORIG, EDIT = DIR / "original", DIR / "editado"
MODEL, CONFIG, LUT = DIR / "modelo.json", DIR / "config.json", DIR / "lut.cube"
VIDEO_EXT = cfg.VIDEO_EXT

# rango de búsqueda de cada control
RANGES = {"exposure": (-1.5, 1.5, 0.4), "contrast": (-50, 60, 16), "highlights": (-100, 60, 24),
          "shadows": (-60, 100, 24), "whites": (-60, 60, 16), "blacks": (-100, 80, 20),
          "temperature": (-80, 80, 10), "tint": (-60, 60, 8), "vibrance": (-30, 100, 14),
          "saturation": (-40, 80, 10)}
QS = [2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 98]
LUMA = np.array([0.2126, 0.7152, 0.0722])

STATE = {"running": False, "done": 0, "total": 0, "stage": "", "error": None}
_lock = threading.Lock()


# ------------------------------------------------------------------ archivos
def _videos(d):
    return {p.stem: p for p in sorted(d.glob("*")) if p.suffix.lower() in VIDEO_EXT and not p.name.startswith(".")} \
        if d.exists() else {}


def pairs():
    o, e = _videos(ORIG), _videos(EDIT)
    model = {p["name"]: p for p in load_model().get("pairs", [])}
    out = []
    for k in sorted(set(o) | set(e)):
        m = model.get(k)
        out.append({"name": k, "original": o[k].name if k in o else None, "editado": e[k].name if k in e else None,
                    "learned": bool(m), "error": (m or {}).get("error")})
    return out


def config():
    try:
        c = json.loads(CONFIG.read_text())
    except Exception:  # noqa
        c = {}
    return {"enabled": c.get("enabled", True), "lut": c.get("lut", False) and LUT.exists(), "kanu": c.get("kanu", True)}


def set_config(**kw):
    DIR.mkdir(exist_ok=True)
    c = config()
    c.update({k: bool(v) for k, v in kw.items() if k in ("enabled", "lut", "kanu")})
    CONFIG.write_text(json.dumps(c))
    load_lut()
    return c


def load_model():
    try:
        return json.loads(MODEL.read_text())
    except Exception:  # noqa
        return {}


def status():
    m = load_model()
    ok = [p for p in m.get("pairs", []) if not p.get("error")]
    return {"pairs": pairs(), "config": config(), "has_lut": LUT.exists(), "learned": len(ok),
            "kanu_clips": kanu_clips(), "kanu_learned": sum(1 for p in ok if p.get("kanu")),
            "date": m.get("date"), "state": dict(STATE)}


def delete(name=None):
    """Borra un par (o todo el estilo si name es None)."""
    if name is None:
        for d in (ORIG, EDIT):
            for p in d.glob("*"):
                p.unlink(missing_ok=True)
        for f in (MODEL, LUT, CONFIG):
            f.unlink(missing_ok=True)
        load_lut()
        return
    for d in (ORIG, EDIT):
        for p in d.glob("*"):
            if p.stem == name:
                p.unlink()
    m = load_model()
    if m:
        m["pairs"] = [p for p in m.get("pairs", []) if p["name"] != name]
        MODEL.write_text(json.dumps(m, indent=1, ensure_ascii=False))


# ------------------------------------------------------------------ medir
def _frames(path, meta, times, knee=True):
    w, h = 320, 180
    fr = [ff._raw_rgb(path, t, w, h, meta if knee else {}) for t in times]
    return np.concatenate([f.reshape(-1, 3) for f in fr])


def _thumbs(path, fps=1):
    raw = ff.run([cfg.FFMPEG, "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale=32:18,format=gray",
                     "-f", "rawvideo", "-"]).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 18 * 32).astype(np.float32)
    a = (a - a.mean(1, keepdims=True)) / (a.std(1, keepdims=True) + 1e-3)   # sin depender del color/brillo
    return a


def _align(orig, edit, mo, me):
    """(desfase en s, velocidad) del editado dentro del original: por si lo recortaste o lo pusiste
    en cámara lenta. Momento t del editado = momento off + t * speed del original."""
    if abs(mo["duration"] - me["duration"]) < 1.0:
        return 0.0, 1.0
    a = _thumbs(orig, fps=4)
    b0 = _thumbs(edit, fps=4)
    best = (np.inf, 0.0, 1.0)
    for speed in (1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.67, 0.6, 0.5):   # lento: el editado dura más
        idx = np.round(np.arange(len(b0)) * speed).astype(int)        # fotograma del original que toca
        n = int(idx[-1]) + 1 if len(idx) else 0
        if n == 0 or n > len(a):
            continue
        for o in range(len(a) - n + 1):
            err = float(np.mean((a[o + idx] - b0) ** 2))
            if err < best[0]:
                best = (err, o / 4, speed)
    return best[1], best[2]


def describe(px):
    """Firma de tono y color de un conjunto de píxeles (lo que se compara)."""
    Y = px @ LUMA
    q = np.percentile(Y, QS)
    mid = (Y > 0.15) & (Y < 0.85)
    sel = px[mid] if mid.sum() > 500 else px
    rb = float((sel[:, 0] - sel[:, 2]).mean())
    gm = float((sel[:, 1] - (sel[:, 0] + sel[:, 2]) / 2).mean())
    sat = float((px.max(1) - px.min(1)).mean())
    return q, rb, gm, sat


def scene_features(px):
    """Tipo de escena del ORIGINAL: con esto se buscan los pares parecidos."""
    q, rb, gm, sat = describe(px)
    return [float(q[0]), float(q[2]), float(q[6]), float(q[10]), float(q[12]), rb, gm, sat]


def _loss(params, src, target, reg=True):
    s = dict(grade.DEFAULTS)
    s.update(params)
    q, rb, gm, sat = describe(grade.apply(src, s))
    tq, trb, tgm, tsat = target
    l = float(np.sum((q - tq) ** 2) * 4 + (rb - trb) ** 2 * 30 + (gm - tgm) ** 2 * 30 + (sat - tsat) ** 2 * 20)
    if reg:  # entre combinaciones que dan lo mismo, la más simple (controles cerca de cero)
        l += 1.5e-5 * sum((v / RANGES[k][2]) ** 2 for k, v in params.items())
    return l


STARTS = [{}, {"shadows": 30, "highlights": -30}, {"shadows": 30, "blacks": 25, "highlights": -30},
          {"contrast": 20}, {"contrast": 15, "blacks": -20}]   # puntos de partida típicos de edición


def _descend(params, src, target):
    step = {k: v[2] for k, v in RANGES.items()}
    best = _loss(params, src, target)
    for _ in range(40):
        improved = False
        for k, (lo, hi, _) in RANGES.items():
            for d in (step[k], -step[k]):
                trial = dict(params)
                trial[k] = min(hi, max(lo, params[k] + d))
                l = _loss(trial, src, target)
                if l < best - 1e-7:
                    best, params, improved = l, trial, True
                    break
        if not improved:
            if max(step[k] / RANGES[k][2] for k in step) < 0.04:
                break
            step = {k: v / 2 for k, v in step.items()}
    return params, best


def fit_pair(src, dst):
    """Ajustes de Kanu que más acercan src a dst. Se prueban varios puntos de partida y gana la
    explicación más simple que reproduce tu edición (descenso por coordenadas con paso decreciente)."""
    rng = np.random.default_rng(0)
    if len(src) > 25000:                       # con 25 mil píxeles basta
        src = src[rng.choice(len(src), 25000, replace=False)]
    target = describe(dst)
    best = None
    for st in STARTS:
        p0 = {k: 0.0 for k in RANGES}
        p0.update(st)
        params, l = _descend(p0, src, target)
        if best is None or l < best[1]:
            best = (params, l)
    params = best[0]
    rounded = {k: (round(v, 2) if k == "exposure" else round(v)) for k, v in params.items()}
    loss = _loss(params, src, target, reg=False)
    rounded.update(fit_hsl(src, dst, params))
    return rounded, loss


# ------------------------------------------------------------------ por color (HSL)
def hue_stats(px):
    """Por cada gama de color: cuánto ocupa, su saturación y su brillo medios (solo píxeles con color)."""
    h, s, v = grade._rgb2hsv(px)
    w = grade.hue_weights(h) * np.clip((s * v - 0.04) / 0.10, 0, 1)[:, None]
    tot = w.sum(0) + 1e-9
    return tot / len(px), (w * s[:, None]).sum(0) / tot, (w * v[:, None]).sum(0) / tot


def fit_hsl(src, dst, base):
    """Después de los ajustes globales: lo que tu edición cambia en cada gama de color por separado
    (p. ej. subir solo los rosados). Devuelve solo las gamas que de verdad cambiaste."""
    rng = np.random.default_rng(1)
    if len(src) > 8000:
        src = src[rng.choice(len(src), 8000, replace=False)]
    s0 = dict(grade.DEFAULTS)
    s0.update(base)
    g = grade.apply(src, s0)
    share_o, sat_t, val_t = hue_stats(dst)
    share_g, _, _ = hue_stats(g)
    cols = [i for i, c in enumerate(grade.HSL_COLORS) if share_g[i] > 0.03 and share_o[i] > 0.03]
    if not cols:
        return {}
    keys = [f"hsl_{c}_{p}" for i, c in enumerate(grade.HSL_COLORS) if i in cols for p in ("s",)]   # la luminancia por gama se confunde con el cielo y las nubes

    def loss(p):
        s = {k: 0.0 for k in grade.HSL_KEYS}
        s.update(p)
        _, sat, val = hue_stats(grade._hsl(g, s))
        # una gama que ocupa poco pesa menos; y se prefiere mover poco (los cambios grandes deben valer la pena)
        return float(sum(min(1.0, (share_g[i] / 0.15) ** 0.5) * (sat[i] - sat_t[i]) ** 2 * 40
                         for i in cols)) + 0.004 * sum((v / 50) ** 2 for v in p.values())

    p, step = {k: 0.0 for k in keys}, 20.0
    best = loss(p)
    while step >= 2.5:
        improved = False
        for k in keys:
            for d in (step, -step):
                t = dict(p)
                t[k] = float(np.clip(p[k] + d, -50, 50))
                l = loss(t)
                if l < best - 1e-7:
                    best, p, improved = l, t, True
                    break
        if not improved:
            step /= 2
    return {k: round(v) for k, v in p.items() if abs(v) >= 5}


# ------------------------------------------------------------------ aprender
def learn():
    """Recalcula el modelo con todos los pares completos (en segundo plano)."""
    with _lock:
        if STATE["running"]:
            return False
        ps = [p for p in pairs() if p["editado"]]       # pares completos o solo el final
        ps += [{"name": n, "kanu": True} for n in kanu_clips()]
        STATE.update(running=True, done=0, total=len(ps), stage="", error=None)
    threading.Thread(target=_learn, args=(ps,), daemon=True).start()
    return True


def look(px):
    """Aspecto de un final, sin depender tanto del contenido: punto negro y blanco, contraste,
    saturación y temperatura/tinte de los medios tonos."""
    q, rb, gm, sat = describe(px)
    return [float(q[0]), float(q[1]), float(q[11]), float(q[12]), float(q[9] - q[3]), sat, rb, gm]


LOOK_W = np.array([3, 3, 3, 3, 4, 3, 6, 6])   # peso de cada rasgo del aspecto


def _learn(ps):
    out = []
    try:
        for i, p in enumerate(ps):
            STATE.update(done=i, stage=p["name"])
            if p.get("kanu"):                         # clip que ajustaste a mano en Kanu: ya es un par perfecto
                try:
                    out.append(_from_kanu(p["name"]))
                except Exception as ex:  # noqa
                    out.append({"name": p["name"], "kanu": True, "error": str(ex)[-200:]})
                continue
            e = EDIT / p["editado"]
            if not p["original"]:                     # solo el final: se aprende su aspecto
                try:
                    me = ff.probe(e)
                    px = _frames(e, me, [me["duration"] * f for f in (0.1, 0.3, 0.5, 0.7, 0.9)], knee=False)
                    out.append({"name": p["name"], "look": look(px)})
                except Exception as ex:  # noqa
                    out.append({"name": p["name"], "error": str(ex)[-200:]})
                continue
            o = ORIG / p["original"]
            try:
                mo, me = ff.probe(o), ff.probe(e)
                off, speed = _align(o, e, mo, me)
                d = min(me["duration"], (mo["duration"] - off) / speed)
                times_e = [d * f for f in (0.1, 0.25, 0.4, 0.55, 0.7, 0.85)]
                src = _frames(o, mo, [off + t * speed for t in times_e], knee=True)
                dst = _frames(e, me, times_e, knee=False)
                params, loss = fit_pair(src, dst)
                out.append({"name": p["name"], "features": scene_features(src), "params": params,
                            "loss": round(loss, 5), "offset": off, "speed": speed})
            except Exception as ex:  # noqa
                out.append({"name": p["name"], "error": str(ex)[-200:]})
        DIR.mkdir(exist_ok=True)
        MODEL.write_text(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M"), "pairs": out}, indent=1,
                                    ensure_ascii=False))
        STATE.update(done=len(ps), stage="listo")
    except Exception as ex:  # noqa
        STATE.update(error=str(ex)[-300:], stage="error")
    STATE["running"] = False


def kanu_clips():
    """Clips de Kanu que ajustaste a mano o aprobaste (y la opción de aprender de ellos está activa)."""
    if not config().get("kanu", True):
        return []
    return [n for n in library.clips() if library.load(n)["status"] in ("manual", "aprobado")]


def _from_kanu(name):
    m, s = library.meta(name), library.load(name)
    src = _frames(library.clip_path(name), m, [m["duration"] * f for f in (0.15, 0.35, 0.5, 0.65, 0.85)])
    return {"name": name, "kanu": True, "features": scene_features(src),
            "params": {k: (round(float(s.get(k) or 0), 2) if k == "exposure" else round(float(s.get(k) or 0))) for k in list(RANGES) + grade.HSL_KEYS}}


# ------------------------------------------------------------------ aplicar
def predict(px, base=None):
    """Ajustes de color con tu estilo para un clip nuevo (o None si no hay estilo activo).
    px: píxeles del original; base: ajustes de la corrección automática.
    Con pares original→editado copia cómo editas; con solo finales lleva el clip hacia su aspecto.
    Devuelve (ajustes, nombres de los videos más parecidos)."""
    if not config()["enabled"]:
        return None
    m = load_model().get("pairs", [])
    ps = [p for p in m if not p.get("error") and p.get("params")]
    looks = [p for p in m if not p.get("error") and p.get("look")]
    if ps:
        F = np.array([p["features"] for p in ps])
        f = np.array(scene_features(px))
        sd = F.std(0) + np.array([0.02, 0.02, 0.03, 0.03, 0.02, 0.01, 0.01, 0.01])
        d = np.sqrt((((F - f) / sd) ** 2).sum(1))
        k = min(5, len(ps))
        idx = np.argsort(d)[:k]
        w = 1 / (d[idx] + 0.3)
        w /= w.sum()
        # confianza: con pocos ejemplos o escenas muy distintas, se mezcla con la corrección automática
        alpha = len(ps) / (len(ps) + 4) * float(np.exp(-d[idx[0]] / 6))
        keys = list(RANGES) + grade.HSL_KEYS                  # también lo que haces por color
        b = {k: float((base or {}).get(k, 0) or 0) for k in keys}
        out = {}
        for key in keys:
            v = float(sum(wi * ps[i]["params"].get(key, 0) for wi, i in zip(w, idx)))
            v = b[key] + alpha * (v - b[key])
            out[key] = round(v, 2) if key == "exposure" else round(v)
        return out, [ps[i]["name"] for i in idx]
    if not looks:
        return None
    return match_look(px, base or {}, looks)


LOOK_SCALE = np.array([0.05, 0.05, 0.06, 0.05, 0.10, 0.06, 0.04, 0.03])   # variación normal entre escenas


def match_look(px, base, looks, strength=0.85):
    """Lleva el clip hacia lo que se REPITE en tus finales (punto negro y blanco, contraste,
    saturación, temperatura). Lo que cambia mucho de un final a otro depende de la escena y no se toca.
    Parte de la corrección automática y no se aleja demasiado de ella."""
    rng = np.random.default_rng(0)
    if len(px) > 25000:
        px = px[rng.choice(len(px), 25000, replace=False)]
    s0 = dict(grade.DEFAULTS)
    s0.update({k: v for k, v in base.items() if k in RANGES})
    cur = np.array(look(grade.apply(px, s0)))
    L = np.array([p["look"] for p in looks])
    mu = L.mean(0)
    sd = L.std(0) if len(L) > 1 else LOOK_SCALE
    consist = np.clip(1 - sd / LOOK_SCALE, 0, 1)            # 1 = siempre igual en tus finales
    target = cur + strength * consist * (mu - cur)
    bound = {k: (0.5 if k == "exposure" else 30) for k in RANGES}

    def loss(p):
        s = dict(grade.DEFAULTS)
        s.update(p)
        v = np.array(look(grade.apply(px, s)))
        return float(((((v - target) / LOOK_SCALE) ** 2) * LOOK_W).sum()) + \
            0.02 * sum(((p[k] - s0[k]) / RANGES[k][2]) ** 2 for k in RANGES)

    params = {k: float(s0[k]) for k in RANGES}
    step = {k: v[2] / 2 for k, v in RANGES.items()}
    best = loss(params)
    for _ in range(30):
        improved = False
        for key, (lo, hi, _) in RANGES.items():
            for dlt in (step[key], -step[key]):
                trial = dict(params)
                trial[key] = min(hi, max(lo, s0[key] - bound[key], min(s0[key] + bound[key], params[key] + dlt)))
                l = loss(trial)
                if l < best - 1e-9:
                    best, params, improved = l, trial, True
                    break
        if not improved:
            if max(step[k] / RANGES[k][2] for k in step) < 0.05:
                break
            step = {k: v / 2 for k, v in step.items()}
    out = {k: (round(v, 2) if k == "exposure" else round(v)) for k, v in params.items()}
    order = np.argsort(np.sqrt((((L - cur) / LOOK_SCALE) ** 2).sum(1)))
    return out, [looks[i]["name"] for i in order[:3]]


# ------------------------------------------------------------------ LUT propia (opcional)
def _parse_cube(path):
    size, data = None, []
    for line in Path(path).read_text(errors="ignore").splitlines():
        t = line.strip().split()
        if not t or t[0].startswith("#"):
            continue
        if t[0].upper() == "LUT_3D_SIZE":
            size = int(t[1])
        elif len(t) == 3:
            try:
                data.append([float(x) for x in t])
            except ValueError:
                pass
    if not size or len(data) != size ** 3:
        raise ValueError("El archivo .cube no es una LUT 3D válida")
    return np.array(data).reshape(size, size, size, 3)   # [b][g][r] (el rojo varía más rápido)


def load_lut():
    """Activa (o quita) la LUT propia en el motor de color."""
    try:
        grade.STYLE_LUT = _parse_cube(LUT) if config()["lut"] else None
    except Exception:  # noqa
        grade.STYLE_LUT = None
    return grade.STYLE_LUT is not None
