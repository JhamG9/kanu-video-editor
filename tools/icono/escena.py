"""Ilustración de la pantalla de carga: el tucán de Kanu entre árboles, palmas de cera y montañas,
con la misma técnica de grabado a plumilla que el icono (líneas cuyo grosor sigue el tono).

Solo usa numpy y ffmpeg. Genera apps/legacy-ui/splash.png (1024 × 1184, vertical).
    python3 tools/icono/escena.py
"""
import subprocess
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "apps" / "legacy-ui" / "splash.png"
FFMPEG = "/opt/homebrew/bin/ffmpeg"

# ------------------------------------------------------------------ el tucán: se dibuja con el mismo código del icono
_src = (HERE / "tucan.py").read_text()
_tucan = {"__file__": str(HERE / "tucan.py")}
exec(compile(_src.split("# ------------------------------------------------------------------ composición")[0],
             "tucan.py", "exec"), _tucan)
T_INK, T_PAPER, TK = _tucan["ink"], _tucan["paper"], _tucan["K"]

# ------------------------------------------------------------------ lienzo de la escena (espacio 1024 × 1184, dibujado al doble)
SW, SH, K = 1024, 1184, 2
Y, X = np.mgrid[0:SH * K, 0:SW * K].astype(np.float32) / K
rng = np.random.default_rng(7)


def noise(scale, seed):
    g = np.random.default_rng(seed).random((int(SH / scale) + 3, int(SW / scale) + 3)).astype(np.float32)
    gx, gy = X / scale, Y / scale
    i, j = gx.astype(int), gy.astype(int)
    fx, fy = gx - i, gy - j
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    return (g[j, i] * (1 - fx) * (1 - fy) + g[j, i + 1] * fx * (1 - fy) + g[j + 1, i] * (1 - fx) * fy
            + g[j + 1, i + 1] * fx * fy)


def noise1(x, scale, seed):
    pts = np.random.default_rng(seed).random(int(SW / scale) + 3)
    return np.interp(x / scale, np.arange(len(pts)), pts)


def lines(u, spacing, tone):
    f = np.abs((u / spacing) % 1.0 - 0.5) * 2
    return (f < np.clip(tone, 0, 1)).astype(np.float32)


def proj(deg):
    a = np.radians(deg)
    return X * np.cos(a) + Y * np.sin(a)


def blur(a, r):
    r = max(1, int(r * K))
    for _ in range(3):
        for ax in (0, 1):
            pad = [(r + 1, r), (0, 0)] if ax == 0 else [(0, 0), (r + 1, r)]
            c = np.cumsum(np.pad(a, pad, mode="edge"), axis=ax)
            a = ((c[2 * r + 1:] - c[:-2 * r - 1]) if ax == 0 else (c[:, 2 * r + 1:] - c[:, :-2 * r - 1])) / (2 * r + 1)
    return a


def edge(mask, w):
    return np.clip(mask - (blur(mask, w) > 0.985), 0, 1)


def dashes(along, length, gap, seed):
    off = noise(length * 1.3, seed) * length * 2
    return (((along + off) / length) % 1.0 > gap).astype(np.float32)


# ------------------------------------------------------------------ colores (los del icono)
BLUE = np.array([128, 166, 208], np.float32) / 255
CREAM = np.array([247, 241, 226], np.float32) / 255
BLACK = np.array([20, 18, 16], np.float32) / 255

img = np.empty((SH * K, SW * K, 3), np.float32)
sky_t = np.clip(Y / 620, 0, 1)
img[:] = BLUE * (1.04 - 0.10 * (1 - sky_t[..., None]) ** 2)          # cielo: un poco más hondo arriba


def paint(mask, color, amount=1.0):
    global img
    a = np.clip(mask * amount, 0, 1)[..., None]
    img = img * (1 - a) + np.asarray(color, np.float32) * a


def ink_col(haze):
    """Tinta que se aclara hacia el azul con la distancia (perspectiva aérea)."""
    return BLACK * (1 - haze) + BLUE * 0.82 * haze


# ------------------------------------------------------------------ cielo: rayado horizontal fino y nubes de papel
sky = lines(Y, 5.6, 0.11 * (1 - sky_t) ** 1.5 + 0.015)
paint(sky * (Y < 640), ink_col(0.72))


def cumulus(puffs, base):
    m = np.zeros_like(X)
    for cx, cy, r in puffs:
        m = np.maximum(m, (np.hypot(X - cx, Y - cy) < r).astype(np.float32))
    m *= (Y < base)
    paint(m, CREAM, 0.95)
    under = np.clip((Y - (base - 40)) / 40, 0, 1)                   # la panza de la nube, en sombra
    paint(m * lines(Y, 4.4, 0.06 + 0.55 * under ** 1.5), ink_col(0.3))
    paint(edge(m, 1.2), ink_col(0.25))


cumulus([(150, 150, 34), (200, 128, 46), (258, 140, 38), (305, 156, 26)], 172)
cumulus([(700, 218, 30), (750, 196, 42), (805, 210, 34), (848, 224, 22)], 238)
cumulus([(560, 92, 18), (590, 82, 24), (622, 92, 18)], 104)


# ------------------------------------------------------------------ montañas (los Andes), de atrás hacia adelante
def ridge(x, base, peaks, rough, seed):
    y = np.full_like(x, base, dtype=np.float32)
    for c, h, w in peaks:
        y -= h * np.exp(-np.abs(x - c) / w)
    return y - rough * (noise1(x, 40, seed) - 0.5) - rough * 0.5 * (noise1(x, 13, seed + 1) - 0.5)


def smooth(v, w):
    k = np.ones(int(w * K)) / int(w * K)
    return np.convolve(np.pad(v, len(k), mode="edge"), k, mode="same")[len(k):-len(k)]


RANGES = [  # base, picos (centro, alto, ancho), aspereza, bruma, tono
    (470, [(120, 150, 90), (380, 210, 120), (660, 120, 80), (900, 190, 110)], 22, 0.66, 0.16),
    (575, [(40, 120, 100), (260, 160, 110), (560, 105, 120), (800, 150, 90), (1010, 90, 70)], 18, 0.46, 0.24),
    (700, [(150, 70, 200), (520, 50, 200), (880, 80, 180)], 10, 0.30, 0.30),
]
for i, (base, peaks, rough, haze, t0) in enumerate(RANGES):
    xs = X[0]
    ry = ridge(xs, base, peaks, rough, 20 + i)
    R = ry[None, :]
    Rs = smooth(ry, 14)[None, :]
    mask = (Y > R).astype(np.float32)
    slope = smooth(np.gradient(smooth(ry, 30)) * K, 50)[None, :]   # >0: ladera que mira a la derecha (en sombra)
    shade = np.clip(slope * 1.4, 0, 1)
    depth = np.clip((Y - R) / 150, 0, 1)
    snow = (i == 0) * np.clip(1 - (Y - R) / 50, 0, 1) * (R < base - 110)
    paint(mask, BLUE * (0.99 - 0.035 * i))
    paint(mask * (snow > 0.05), CREAM, 0.9)
    tone = (t0 + 0.42 * shade) * (1 - 0.55 * depth * (i < 2)) + 0.05 * (noise(22, 40 + i) - 0.5)
    contour = lines(Y - Rs, 4.8, tone * (1 - 0.6 * snow))
    hatch = lines(proj(58), 4.2, (shade - 0.25) * 0.9 * (1 - 0.5 * depth)) * (1 - snow)
    paint(mask * np.maximum(contour, hatch), ink_col(haze))
    paint(edge(mask, 1.2 + 0.3 * i), ink_col(haze * 0.75))

# ------------------------------------------------------------------ palmas de cera (como en el Quindío)
def wax_palm(bx, by, h, lean, haze, seed):
    t = np.clip((by - Y) / h, 0, 1)
    cx = bx + lean * t ** 2 * h * 0.12
    w = 3.4 - 1.2 * t
    trunk = ((np.abs(X - cx) < w) & (Y < by) & (Y > by - h)).astype(np.float32)
    rings = lines(Y + 0.3 * X, 7.0, 0.45)
    paint(trunk * np.maximum(rings, (np.abs(X - cx) > w * 0.25).astype(np.float32)), ink_col(haze))
    top = (bx + lean * h * 0.12, by - h)
    r = np.random.default_rng(seed)
    crown = np.zeros_like(X)
    for k in range(14):                                     # hojas: arcos que caen
        a = -np.pi / 2 + (k - 6.5) / 6.5 * 2.4 + r.normal(0, 0.08)
        L = 70 + 28 * r.random()
        s = np.linspace(0, 1, 46)
        px = top[0] + np.cos(a) * L * s
        py = top[1] + np.sin(a) * L * s + 46 * s ** 2 * (1 + abs(np.cos(a)))
        for j in range(0, 46, 2):
            d = np.hypot(X - px[j], Y - py[j])
            crown = np.maximum(crown, (d < 2.6 * (1 - s[j]) + 1.0).astype(np.float32))
            if 6 < j < 42:                                 # foliolos
                crown = np.maximum(crown, ((np.abs((X - px[j]) * np.sin(a) - (Y - py[j]) * np.cos(a)) < 0.8)
                                           & (np.hypot(X - px[j], Y - py[j]) < 13 * (1 - s[j]) + 3)).astype(np.float32))
    paint(crown, ink_col(haze))


for bx, by, h, lean, haze, seed in ((612, 702, 330, 1.0, 0.25, 1), (700, 712, 270, -0.8, 0.32, 2), (980, 690, 300, -0.5, 0.28, 3)):
    wax_palm(bx, by, h, lean, haze, seed)


# ------------------------------------------------------------------ árboles: copas hechas de matas, cada una con luz arriba a la izquierda
def canopy(blobs, haze, t0, seed, cs=26.0):
    """Copa de árbol de grabado: muchas matas redondas que se tapan unas a otras (de atrás hacia adelante)."""
    r = np.random.default_rng(seed)
    m = np.zeros_like(X)
    for cx, cy, rr in blobs:
        m = np.maximum(m, (np.hypot(X - cx, Y - cy) < rr * 0.92).astype(np.float32))
    xs = np.array([b[0] for b in blobs]); ys = np.array([b[1] for b in blobs]); rs = np.array([b[2] for b in blobs])
    pts = []
    for cx, cy, rr in blobs:                                  # matas repartidas por cada bola de la copa
        n = int((rr / cs) ** 2 * 1.6) + 3
        for _ in range(n):
            a, d = r.random() * 2 * np.pi, rr * np.sqrt(r.random()) * 0.95
            pts.append((cx + np.cos(a) * d, cy + np.sin(a) * d, cs * (0.75 + 0.5 * r.random())))
    pts.sort(key=lambda p: p[1] + 0.4 * p[0])                 # las de arriba primero: las de abajo las tapan
    gx0, gy0 = xs.min() - rs.max(), ys.min() - rs.max()
    gl = np.clip(1.05 - ((X - gx0) / 500 + (Y - gy0) / 650), 0, 1)     # luz general de la copa
    for cx, cy, rr in pts:
        x0, x1 = int(max(0, (cx - rr * 1.3) * K)), int(min(X.shape[1], (cx + rr * 1.3) * K))
        y0, y1 = int(max(0, (cy - rr * 1.3) * K)), int(min(X.shape[0], (cy + rr * 1.3) * K))
        if x1 <= x0 or y1 <= y0:
            continue
        xx, yy = X[y0:y1, x0:x1], Y[y0:y1, x0:x1]
        ang = np.arctan2(yy - cy, xx - cx)
        rad = rr * (1 + 0.09 * np.abs(np.sin(ang * 7 + cx)))
        d = np.hypot(xx - cx, yy - cy)
        mk = (d < rad).astype(np.float32)
        side = np.clip(((xx - cx) * 0.6 + (yy - cy) * 0.8) / rr, -1, 1)          # -1 luz … 1 sombra
        tone = t0 + 0.38 * side + 0.25 * (1 - gl[y0:y1, x0:x1]) - 0.12
        ln = lines(proj(-35)[y0:y1, x0:x1] + 4 * np.sin((yy + xx) / 9), 4.4, tone)
        rim = ((d > rad - 1.6) & (d < rad) & (side > -0.2)).astype(np.float32)   # contorno solo del lado en sombra
        sub = img[y0:y1, x0:x1]
        base = BLUE * (0.95 - 0.06 * np.clip(side, 0, 1)[..., None])
        sub[:] = sub * (1 - mk[..., None]) + base * mk[..., None]
        a = np.clip(np.maximum(ln, rim) * mk, 0, 1)[..., None]
        sub[:] = sub * (1 - a) + ink_col(haze) * a
    return m


def trunk(pts, w0, w1, haze):
    pts = np.array(pts, float)
    t = np.linspace(0, 1, 120)
    seg = np.array([np.interp(t, np.linspace(0, 1, len(pts)), pts[:, k]) for k in (0, 1)]).T
    m = np.zeros_like(X)
    for (x0, y0), tt in zip(seg, t):
        m = np.maximum(m, (np.hypot(X - x0, Y - y0) < w0 + (w1 - w0) * tt).astype(np.float32))
    bark = lines(X + 6 * np.sin(Y / 23) + 3 * noise(10, 77), 4.2, 0.55 + 0.3 * np.clip((X - seg[:, 0].mean()) / 30, -1, 1))
    paint(m, BLUE * 0.9)
    paint(m * np.maximum(bark, edge(m, 1.6)), ink_col(haze))


# arboleda lejana sobre las lomas
for cx in range(-20, 1060, 44):
    yb = ridge(np.array([cx], np.float32), *RANGES[2][:3], 22)[0]
    if rng.random() < 0.7:
        r0 = 18 + 10 * rng.random()
        canopy([(cx, yb + 8, r0), (cx + 16, yb + 12, r0 * 0.8)], 0.36, 0.40, int(cx) + 100, cs=11.0)

# arbusto detrás del tucán, a la derecha
canopy([(930, 900, 120), (1010, 860, 110), (860, 980, 110), (1000, 1010, 130)], 0.10, 0.42, 300, cs=30.0)

# árbol grande a la izquierda que enmarca la escena
trunk([(150, 1200), (165, 1000), (140, 820), (175, 640)], 34, 16, 0.0)
trunk([(162, 760), (240, 690), (300, 640)], 12, 5, 0.0)
canopy([(40, 420, 150), (170, 360, 140), (300, 430, 110), (60, 610, 160), (230, 570, 120), (-10, 800, 150),
        (120, 760, 110)], 0.0, 0.42, 500, cs=34.0)

# ------------------------------------------------------------------ el tucán (mismo dibujo del icono), en primer plano
S, OX, OY = 0.74, 118, 436
ix, iy = (X - OX) / S * TK, (Y - OY) / S * TK
ok = (ix >= 0) & (iy >= 0) & (ix < T_INK.shape[1] - 1) & (iy < T_INK.shape[0] - 1)
ixc, iyc = np.clip(ix, 0, T_INK.shape[1] - 2), np.clip(iy, 0, T_INK.shape[0] - 2)
i0, j0 = ixc.astype(int), iyc.astype(int)
fx, fy = ixc - i0, iyc - j0


def sample(a):
    v = (a[j0, i0] * (1 - fx) * (1 - fy) + a[j0, i0 + 1] * fx * (1 - fy) + a[j0 + 1, i0] * (1 - fx) * fy
         + a[j0 + 1, i0 + 1] * fx * fy)
    return v * ok


paper, ink = sample(T_PAPER), sample(T_INK)
sh = blur(paper, 16)
sy, sx = 12 * K, 9 * K
sh = np.pad(sh, ((sy, 0), (0, sx)))[:SH * K, sx:]
img *= (1 - 0.30 * sh[..., None])                          # sombra suave del tucán sobre el fondo
paint(paper, CREAM)
paint(ink, BLACK)

# ------------------------------------------------------------------ salida
out = img.reshape(SH, K, SW, K, 3).mean(axis=(1, 3))
raw = (np.clip(out, 0, 1) * 255).round().astype(np.uint8).tobytes()
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{SW}x{SH}", "-i", "-",
                str(OUT)], input=raw, check=True)
print("listo:", OUT)
