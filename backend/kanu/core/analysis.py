"""Análisis automático de un clip: color, ruido, vibración e inclinación."""
import math

import numpy as np

from kanu import config
from kanu.core import grade
from kanu.infra import ffmpeg as ff


def estimate_noise(path, meta):
    """Ruido (en niveles de 8 bits) medido a resolución nativa en zonas planas y oscuras."""
    W, H = meta["width"], meta["height"]
    sig = []
    for frac in (0.3, 0.7):
        img = ff._raw_rgb(path, meta["duration"] * frac, W, H, meta)
        Y = (img @ np.array([0.2126, 0.7152, 0.0722])) * 255
        k = Y[:-2, :-2] - 2 * Y[:-2, 1:-1] + Y[:-2, 2:] - 2 * Y[1:-1, :-2] + 4 * Y[1:-1, 1:-1] \
            - 2 * Y[1:-1, 2:] + Y[2:, :-2] - 2 * Y[2:, 1:-1] + Y[2:, 2:]
        gx = np.abs(Y[1:-1, 2:] - Y[1:-1, :-2])
        gy = np.abs(Y[2:, 1:-1] - Y[:-2, 1:-1])
        grad = gx + gy
        center = Y[1:-1, 1:-1]
        mask = (center > 8) & (center < 140)
        if mask.sum() < 5000:
            mask = center > 8
        flat = mask & (grad < np.percentile(grad[mask], 25))
        if flat.sum() < 2000:
            continue
        sig.append(math.sqrt(math.pi / 2) / 6 * np.abs(k[flat]).mean())
    return round(float(np.median(sig)), 2) if sig else 0.0


def noise_level(sigma):
    if sigma < 1.4:
        return "off"
    if sigma < 2.2:
        return "suave"
    if sigma < 3.2:
        return "media"
    return "fuerte"


def analyze(path, meta, step=lambda name: None):
    """Corrección automática natural para stock: limpia, sin look cinematográfico.
    step(nombre) avisa en qué etapa va, para mostrar el progreso."""
    step("luz")
    w, h = 480, 270
    frames = [ff._raw_rgb(path, meta["duration"] * f, w, h, meta) for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    px = np.concatenate([f.reshape(-1, 3) for f in frames])
    Y = px @ np.array([0.2126, 0.7152, 0.0722])
    # Quemado: con los superblancos recuperados el blanco de la cámara queda en ~0.964, no en 1
    clip_hi = float((Y > (0.955 if ff.knee(meta) else 0.97)).mean())
    p99 = float(np.percentile(Y, 99))
    # El tono se mide sin el cielo quemado, que si no domina todas las cifras
    G = Y[Y < 0.8] if (Y < 0.8).mean() > 0.3 else Y
    p = {q: float(np.percentile(G, q)) for q in (1, 10, 25, 50, 75)}
    p[99] = p99
    s = dict(grade.DEFAULTS)
    why = []

    # Exposición: solo si la escena está claramente oscura o clara
    if p[50] < 0.33:
        e = round(min(0.8, math.log2((0.42 / max(p[50], 0.05)) ** 2.2) * 0.5), 2)
        # sin quemar el cielo: se baja la subida hasta que casi nada pase del blanco
        while e > 0 and float((Y * 2 ** (e / 2.2) > 0.97).mean()) > 0.004:
            e = round(e - 0.05, 2)
        if e >= 0.1:
            s["exposure"] = e
            why.append("escena oscura → subo exposición" + (" (con cuidado del cielo)" if e < 0.3 else ""))
    elif p[25] > 0.6:  # todo claro, no solo el cielo
        # mucha zona quemada (neblina, cielo blanco): se baja más para que no se vea lavado
        s["exposure"] = round(max(-0.8 if clip_hi > 0.4 else -0.5, math.log2((0.5 / p[50]) ** 2.2) * 0.5), 2)
        why.append("escena muy clara → bajo exposición")

    # Altas luces / cielo
    hl = 0
    if clip_hi > 0.03:  # mucho blanco quemado
        hl = -round(min(30, 10 + clip_hi * 100))
    if p[50] > 0.55 and clip_hi < 0.2:  # escena clara sin quemar (ciudad con bruma, neblina): bajarlas devuelve detalle
        hl = min(hl, -round(min(80, (p[50] - 0.5) * 650)))  # criterio del usuario en C0254: -83
    if hl:
        s["highlights"] = hl
        why.append("cielo o luces muy brillantes → recupero altas luces")
    elif p[99] < 0.85:
        s["whites"] = round(min(40, (0.92 - p[99]) * 350))
        why.append("blancos apagados → subo blancos")

    # Punto negro: quita el velo y la neblina
    if p[1] > 0.03:
        s["blacks"] = -round(min(50, (p[1] - 0.01) * 350))
        why.append("negros lavados → bajo negros")

    # Sombras
    if p[10] < 0.12:
        s["shadows"] = round(min(40, (0.12 - p[10]) * 300))
        why.append("sombras cerradas → abro sombras")

    # Contraste
    iqr = p[75] - p[25]
    hazy = p[1] > 0.1
    s["contrast"] = round(min(35, max(12 if hazy else 5, (0.32 - iqr) * 150)))
    if iqr < 0.25:
        why.append("imagen plana → más contraste")

    # Balance de blancos con píxeles casi neutros (corrección parcial)
    lin = px ** 2.2
    chroma = px.max(axis=1) - px.min(axis=1)
    neutral = (Y > 0.15) & (Y < 0.75) & (chroma < 0.1)  # sin cielo ni neblina brillante
    if neutral.sum() > 2000:
        r, g, b = lin[neutral].mean(axis=0)
        temp = -math.log(r / b) / 0.24 * 100 * 0.5
        tint = math.log(g / math.sqrt(r * b)) / 0.08 * 100 * 0.4
        s["temperature"] = round(max(-15, min(15, temp)))
        s["tint"] = round(max(-12, min(12, tint)))
        if abs(s["temperature"]) >= 5 or abs(s["tint"]) >= 5:
            why.append("dominante de color → corrijo balance de blancos")

    # Color: vivo pero natural
    sat = float(chroma.mean())
    s["vibrance"] = 25 if sat < 0.12 else (15 if sat < 0.25 else 5)
    s["saturation"] = 5 if sat < 0.2 else 0
    if sat < 0.12:
        why.append("colores apagados → subo intensidad")

    if (meta.get("white_peak") or 0) > 0.925:
        why.insert(0, "superblancos de la cámara → recupero el detalle del cielo")

    # Escena con sombras profundas y cielo brillante (aérea con sol, típica del dron): no hundir los negros.
    # Aprendido del ajuste a mano del usuario en DJI 0353: sombras +48, negros +36, altas luces −40,
    # contraste +10, intensidad 15, la mitad de corrección de tinte y reducción de ruido media.
    deep = p[1] < 0.09 and p[10] < 0.2
    if deep:
        s["shadows"] = round(min(50, max(0, (0.20 - p[10]) * 700)))
        s["blacks"] = round(min(40, max(0, (0.10 - p[1]) * 800)))
        s["highlights"] = min(s["highlights"], -round(min(40, max(0, (p99 - 0.75) * 300))))
        s["contrast"] = max(s["contrast"], 10)
        s["vibrance"] = min(s["vibrance"], 15)
        s["tint"] = round(s["tint"] * 0.5)
        why = [w for w in why if "negros" not in w and "sombras" not in w]
        why.append("sombras profundas y cielo brillante → abro sombras, levanto negros y bajo las luces (como tu ajuste del dron)")

    # comprobación final con la corrección completa: si quema el cielo, se baja la exposición
    sample = px[::7]
    burnt = lambda st: float(((grade.apply(sample, st) @ np.array([0.2126, 0.7152, 0.0722])) > 0.985).mean())
    base_burn = burnt(dict(grade.DEFAULTS))
    while s["exposure"] > 0 and burnt(s) > max(0.004, base_burn * 1.5):
        s["exposure"] = round(s["exposure"] - 0.05, 2)
    if s["exposure"] <= 0.05 and any("subo exposición" in w for w in why):
        s["exposure"] = 0.0
        why = [w for w in why if "subo exposición" not in w] + ["escena oscura, pero subir la exposición quemaría el cielo → la dejo"]

    step("ruido")
    sigma = estimate_noise(path, meta)
    step("vibracion")
    jit, sway = measure_jitter(path, meta)
    # Para stock la toma debe parecer de trípode: a mano casi siempre hace falta Media o más
    if jit < 0.2 and sway < 1.0:
        stab = "off"
    elif jit < 0.6 and sway < 3:
        stab = "suave"
    elif jit < 1.5 and sway < 9:
        stab = "media"
    else:
        stab = "fuerte"
    if stab != "off":
        why.append(f"vibración {jit:.1f} px y vaivén {sway:.1f} px → estabilización {stab}")
    stats = {k: round(v, 3) for k, v in p.items()}
    stats.update(clip_hi=round(clip_hi, 3), sat=round(sat, 3), noise=sigma, jitter=jit, sway=sway)
    lvl = noise_level(sigma)
    if deep and s["shadows"] >= 30 and lvl in ("off", "suave"):
        lvl = "media"
        why.append("sombras abiertas → reduzco el ruido")
    return s, lvl, sigma, why, stats, stab


def _phase_shift(a, b):
    A, B = np.fft.fft2(a), np.fft.fft2(b)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-9
    r = np.fft.ifft2(R).real
    y, x = np.unravel_index(r.argmax(), r.shape)
    h, w = r.shape

    def sub(c, line, n):
        l, cc, rr = line[(c - 1) % n], line[c], line[(c + 1) % n]
        den = l - 2 * cc + rr
        return c + (0.5 * (l - rr) / den if den != 0 else 0)

    xs, ys = sub(x, r[y, :], w), sub(y, r[:, x], h)
    return (xs + w / 2) % w - w / 2, (ys + h / 2) % h - h / 2


def measure_jitter(path, meta, seconds=30.0):
    """Vibración media (píxeles en 4K): movimiento de cámara menos su versión suavizada.

    Mide el clip entero (hasta 30 s): con solo unos segundos se subestima mucho el vaivén.
    """
    w, h = 480, 270
    t0 = max(0, (meta["duration"] - seconds) / 2)
    n = int(seconds * min(meta["fps"], 60))
    raw = ff.run([config.FFMPEG, "-v", "error", "-ss", f"{t0:.2f}", "-i", str(path), "-frames:v", str(n),
               "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"]).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)
    if len(f) < 20:
        return 0.0
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    d = np.array([_phase_shift((f[i] - f[i].mean()) * win, (f[i + 1] - f[i + 1].mean()) * win)
                  for i in range(len(f) - 1)])
    traj = np.cumsum(d, 0)
    k = 31
    ker = np.ones(k) / k
    sm = np.stack([np.convolve(np.pad(traj[:, j], (k // 2, k // 2), mode="edge"), ker, "valid") for j in range(2)], 1)
    k2 = 121  # vaivén lento (0.5–2 s): es lo que más se nota como "tiembla" en tomas a mano
    sm2 = np.stack([np.convolve(np.pad(sm[:, j], (k2 // 2, k2 // 2), mode="edge"), np.ones(k2) / k2, "valid")
                    for j in range(2)], 1)
    f = meta["width"] / w
    return round(float(np.abs(traj - sm).mean() * f), 2), round(float(np.abs(sm - sm2).mean() * f), 2)


def detect_tilt(path, meta, rng=8.0):
    """Mide cuánto está girada la toma (grados, positivo = horario), como hace un editor a ojo.

    Usa los bordes casi verticales (edificios, postes, troncos). Al grabar mirando hacia arriba o
    hacia abajo, las verticales se abren hacia los lados por la perspectiva; por eso se ajusta
    `inclinación = giro + k·x` y solo se toma el giro (lo que se ve en el centro del cuadro).
    Devuelve (ángulo para corregir, confianza 0-1, cantidad de bordes).
    """
    W, H = 1920, 1080
    ds, xs, ws = [], [], []
    for f in (0.2, 0.5, 0.8):
        g = ff._raw_rgb(path, meta["duration"] * f, W, H, meta).mean(2)
        gx = np.zeros_like(g); gy = np.zeros_like(g)
        gx[1:-1, 1:-1] = (g[1:-1, 2:] - g[1:-1, :-2]) * 2 + g[:-2, 2:] - g[:-2, :-2] + g[2:, 2:] - g[2:, :-2]
        gy[1:-1, 1:-1] = (g[2:, 1:-1] - g[:-2, 1:-1]) * 2 + g[2:, :-2] - g[:-2, :-2] + g[2:, 2:] - g[:-2, 2:]
        mag = np.hypot(gx, gy)
        a = (np.degrees(np.arctan2(gy, gx)) + 90) % 180 - 90   # gradiente casi horizontal = borde vertical
        k = (mag > np.percentile(mag, 97)) & (np.abs(a) <= rng)
        yy, xx = np.nonzero(k)
        ds.append(a[k]); xs.append((xx - W / 2) / (W / 2)); ws.append(mag[k])
    d, x, w = np.concatenate(ds), np.concatenate(xs), np.concatenate(ws)
    if len(d) < 2000:
        return 0.0, 0.0, int(len(d))
    d0, x0 = d.copy(), x.copy()
    for _ in range(4):
        A = np.stack([np.ones_like(d), x], 1)
        sol = np.linalg.lstsq(A * np.sqrt(w)[:, None], d * np.sqrt(w), rcond=None)[0]
        r = d - A @ sol
        keep = np.abs(r) < 2.5 * 1.4826 * np.median(np.abs(r))
        d, x, w = d[keep], x[keep], w[keep]
    # confianza: cuántos bordes quedan pegados al modelo frente a lo que daría el azar (sin líneas rectas)
    near = np.mean(np.abs(d0 - (sol[0] + sol[1] * x0)) < 0.75)
    chance = 1.5 / (2 * rng)
    conf = float(np.clip((near / chance - 1) / 1.5, 0, 1))
    return round(float(-sol[0]), 1), round(conf, 2), int(len(d0))
