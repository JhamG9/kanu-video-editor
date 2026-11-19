"""Icono de Kanu: tucán en estilo grabado fino (como una ilustración a plumilla).

Solo usa numpy y ffmpeg. Genera editor/static/icon.png (1024 px).
    python3 tools/icono/tucan.py
"""
import subprocess
from pathlib import Path

import numpy as np

N = 2048                      # se dibuja al doble y se reduce (antialias)
K = N / 1024                  # las coordenadas están en espacio 1024
OUT = Path(__file__).resolve().parents[2] / "apps" / "legacy-ui" / "icon.png"
FFMPEG = "/opt/homebrew/bin/ffmpeg"

SHIFT = 140                   # el dibujo se hace en un lienzo más ancho y se corre a la izquierda
W = int((1024 + SHIFT) * K)
Y, X = np.mgrid[0:N, 0:W].astype(np.float32) / K


# ------------------------------------------------------------------ utilidades
def bez(p0, p1, p2, p3, n=48):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.array, (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def path(start, *curves):
    pts, cur = [np.array([start], float)], start
    for c in curves:
        seg = bez(cur, *c) if len(c) == 3 else np.array([cur, c[0]], float)
        pts.append(seg[1:])
        cur = c[-1]
    return np.vstack(pts)


def fill(poly):
    p = poly * K
    m = np.zeros((N, W), bool)
    x0, y0 = p[:, 0], p[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    for r in range(int(max(0, y0.min())), int(min(N, y0.max() + 1))):
        y = r + 0.5
        c = ((y0 <= y) & (y1 > y)) | ((y1 <= y) & (y0 > y))
        if not c.any():
            continue
        xs = np.sort(x0[c] + (y - y0[c]) * (x1[c] - x0[c]) / (y1[c] - y0[c]))
        for a, b in zip(xs[::2], xs[1::2]):
            m[r, max(0, int(round(a))):min(W, int(round(b)))] = True
    return m.astype(np.float32)


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


def lines(u, spacing, tone):
    """Línea de grabado: grosor proporcional al tono (0 papel … 1 tinta)."""
    f = np.abs((u / spacing) % 1.0 - 0.5) * 2
    return (f < np.clip(tone, 0, 1)).astype(np.float32)


def dist(cx, cy):
    return np.hypot(X - cx, Y - cy)


def proj(angle_deg):
    a = np.radians(angle_deg)
    return X * np.cos(a) + Y * np.sin(a)


def noise(scale, seed=0):
    """Ruido suave para romper la regularidad de los trazos."""
    g = np.random.default_rng(seed).random((int(1024 / scale) + 3, int((1024 + SHIFT) / scale) + 3)).astype(np.float32)
    gx, gy = X / scale, Y / scale
    i, j = gx.astype(int), gy.astype(int)
    fx, fy = gx - i, gy - j
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    return (g[j, i] * (1 - fx) * (1 - fy) + g[j, i + 1] * fx * (1 - fy) + g[j + 1, i] * (1 - fx) * fy
            + g[j + 1, i + 1] * fx * fy)


def dashes(along, length, gap, seed):
    """Rompe las líneas en trazos cortos escalonados (textura de pluma)."""
    off = noise(length * 1.3, seed) * length * 2
    return (((along + off) / length) % 1.0 > gap).astype(np.float32)


# ------------------------------------------------------------------ silueta (busto mirando a la derecha)
head_body = path((205, 1060), ((240, 900), (280, 760), (282, 610)), ((284, 470), (300, 330), (380, 268)),
                 ((440, 222), (530, 214), (582, 246)), ((596, 300), (600, 380), (596, 452)),
                 ((640, 520), (700, 610), (712, 720)), ((724, 840), (716, 950), (740, 1060)))
bib = path((596, 440), ((650, 500), (700, 590), (706, 690)), ((712, 760), (690, 800), (650, 812)),
           ((580, 828), (500, 790), (468, 720)), ((440, 650), (452, 560), (500, 498)),
           ((530, 462), (566, 446), (596, 440)))
band = path((468, 720), ((500, 790), (580, 828), (650, 812)), ((690, 800), (708, 780), (712, 760)),
            ((716, 800), (716, 830), (714, 858)), ((640, 880), (520, 860), (452, 790)))
eye_skin = path((448, 318), ((468, 270), (548, 262), (572, 300)), ((590, 336), (580, 390), (536, 404)),
                ((488, 414), (446, 384), (448, 318)))
upper = path((584, 262), ((700, 210), (880, 210), (982, 246)), ((1052, 272), (1092, 330), (1102, 422)),
             ((1010, 384), (800, 374), (598, 394)), ((580, 344), (576, 300), (584, 262)))
lower = path((598, 394), ((800, 374), (1010, 384), (1102, 422)), ((1040, 424), (850, 430), (712, 436)),
             ((654, 438), (618, 441), (596, 446)), ((596, 426), (597, 410), (598, 394)))
cut_curve = bez((598, 394), (800, 374), (1010, 384), (1102, 422), 80)
wing = path((300, 560), ((330, 640), (400, 760), (430, 1060)), ((205, 1060),),
            ((240, 900), (276, 740), (300, 560)))

M = {k: fill(v) for k, v in dict(body=head_body, bib=bib, band=band, skin=eye_skin, upper=upper,
                                    lower=lower, wing=wing).items()}
M["body"] = np.clip(M["body"] + M["bib"] + M["band"], 0, 1)
M["wing"] *= M["body"]
beak = np.clip(M["upper"] + M["lower"], 0, 1)
M["tip"] = beak * (X > 1030 + 0.010 * (Y - 335) ** 2)
EYE = (515, 336)

ink = np.zeros((N, W), np.float32)
paper = np.clip(M["body"] + beak, 0, 1)
light = np.clip(1.15 - (X - 250) / 800 - (Y - 180) / 1100, 0, 1)        # luz de arriba a la izquierda
n1 = noise(18, 1)

# ------------------------------------------------------------------ plumaje negro
plum = M["body"] * (1 - np.clip(M["bib"] + M["band"] + M["skin"], 0, 1))
vol = blur(M["body"], 70)
rim = np.clip(1 - blur(M["body"], 12), 0, 1) * M["body"]                 # brillo fino en el borde
glow = np.exp(-(((X - 400) / 170) ** 2 + ((Y - 300) / 120) ** 2))       # luz sobre cabeza y nuca
tone = 0.95 - 0.40 * glow - 0.16 * light * vol - 0.35 * rim + 0.08 * (n1 - 0.5) + 0.08 * np.clip((Y - 600) / 300, 0, 1)
# capa 1: trazos de pluma que salen del pico y se curvan hacia atrás
cx, cy = 600, 330
r = dist(cx, cy)
ang = np.arctan2(Y - cy, X - cx)
u1 = r + 14 * np.sin(ang * 3.0)
stroke = dashes(ang * r, 22, 0.18, 2)
h1 = lines(u1, 5.4, tone) * np.where(tone < 0.8, stroke, 1.0)
# capa 2: cruzado en las zonas más oscuras
h2 = lines(proj(-38) + 6 * np.sin(proj(52) / 40), 6.2, (tone - 0.55) * 1.6)
# plumas del pecho/espalda: escamas pequeñas con borde claro
cs = 30.0
row = np.floor(Y / (cs * 0.72))
n2 = noise(40, 5)
fx = ((X / cs + 0.5 * (row % 2) + 0.5 * (n2 - 0.5)) % 1.0) - 0.5
fy = (Y / (cs * 0.72)) % 1.0
scales = np.exp(-((np.hypot(fx, (fy - 0.1) * 1.2) - 0.5) / 0.06) ** 2) * np.clip((Y - 520) / 120, 0, 1)
ink += plum * np.clip(np.maximum(h1, h2) - scales * (0.25 + 0.5 * light) * (n1 > 0.35), 0, 1)

# ala: plumas largas, líneas a lo largo, borde de cada pluma claro
fu = proj(-14) / 30.0
fr = (fu % 1.0) - 0.5
k = np.floor(fu)
fv = proj(76)
tipline = np.exp(-(((fv - (980 + 55 * np.sin(k * 2.1))) - 160 * fr ** 2) / 3.0) ** 2)
sep = np.exp(-((np.abs(fr) - 0.5) / 0.035) ** 2)
tone_w = 0.93 - 0.16 * light - 0.5 * np.clip(sep + tipline, 0, 1)
ink = ink * (1 - M["wing"]) + M["wing"] * lines(fv, 5.0, tone_w)

# ------------------------------------------------------------------ pechera blanca
bv = blur(M["bib"], 34)
tone = 0.03 + 0.55 * np.clip(1 - bv, 0, 1) ** 1.5 + 0.10 * (1 - light)
ink += M["bib"] * lines(dist(330, 610) + 4 * np.sin(Y / 23), 5.2, tone) * dashes(proj(80), 26, 0.1, 3)
ink += M["bib"] * lines(dist(330, 610), 5.2, 0.12 * (n1 > 0.62)) * (bv < 0.9)   # plumitas sueltas
# franja inferior (roja en el tucán real): tono medio
tone = 0.45 + 0.25 * (1 - blur(M["band"], 12))
ink += M["band"] * lines(dist(560, 1300), 4.8, tone)

# ------------------------------------------------------------------ piel del ojo y ojo
sv = blur(M["skin"], 14)
stip = (np.hypot((X % 6.5) - 3.25 + 1.2 * (n1 - 0.5), (Y % 6.5) - 3.25) < 0.7 + 1.7 * (1 - sv)).astype(np.float32)
ink += M["skin"] * stip
d_eye = dist(*EYE)
ink += ((d_eye > 24) & (d_eye < 29)).astype(np.float32)                        # anillo
ink += (d_eye < 22) * lines(d_eye, 2.6, 0.75 + 0.25 * (d_eye < 12))           # iris
ink += (d_eye < 11).astype(np.float32)                                         # pupila
ink *= 1 - (dist(EYE[0] + 7, EYE[1] - 8) < 5.5).astype(np.float32)             # brillo
wr = np.exp(-((d_eye - 38) / 1.3) ** 2) + np.exp(-((d_eye - 50) / 1.1) ** 2) * 0.8
ink += M["skin"] * ((wr * (np.cos(np.arctan2(Y - EYE[1], X - EYE[0]) * 2) > -0.3)) > 0.5)

# ------------------------------------------------------------------ pico
bvk = blur(beak, 20)
top_curve = 212 + 0.0007 * (X - 830) ** 2
hl = np.exp(-((Y - (top_curve + 28)) / 20) ** 2)                               # reflejo arriba
tone_up = (0.10 + 0.28 * (1 - bvk) + 0.34 * np.clip((Y - 310) / 60, 0, 1) - 0.12 * hl
           + 0.30 * np.clip((650 - X) / 70, 0, 1) + 0.05 * (n1 - 0.5))
u_up = dist(850, 1100)
ink += M["upper"] * (1 - M["tip"]) * lines(u_up, 4.8, tone_up)
ink += M["upper"] * (1 - M["tip"]) * lines(proj(84) + 25 * np.sin(X / 90), 22.0, 0.05 * (n1 > 0.45))  # estrías
tone_lo = 0.36 + 0.30 * (1 - bvk) + 0.10 * np.clip((X - 700) / 300, 0, 1)
ink += M["lower"] * (1 - M["tip"]) * lines(dist(850, 1180), 4.4, tone_lo)
tip_t = 0.82 - 0.25 * hl                                                        # punta oscura
ink += M["tip"] * np.maximum(lines(u_up, 4.6, tip_t), lines(proj(55), 5.5, tip_t - 0.25))
base = beak * (X < 612 + 0.0006 * (Y - 340) ** 2)                              # franja de la base
ink = np.maximum(ink, base * lines(proj(4), 3.8, 0.88))
cutd = np.full((N, W), 1e9, np.float32)                                         # comisura
for x0, y0 in cut_curve[::2]:
    cutd = np.minimum(cutd, np.hypot(X - x0, Y - y0))
ink = np.maximum(ink, beak * (cutd < 2.2))
teeth = np.zeros((N, W), np.float32)                                            # bordes dentados
for i in range(10, 66, 5):
    (x0, y0), (x1, y1) = cut_curve[i], cut_curve[i + 3]
    teeth += fill(np.array([(x0, y0), ((x0 + x1) / 2, (y0 + y1) / 2 + 7), (x1, y1)], float))
ink = np.maximum(ink, np.clip(teeth, 0, 1) * beak)

# ------------------------------------------------------------------ contornos finos
for key, w in (("body", 2.6), ("upper", 2.4), ("lower", 2.4), ("bib", 1.6), ("skin", 1.4), ("band", 1.4)):
    ink = np.maximum(ink, edge(M[key], w))
ink = np.clip(ink, 0, 1)

# ------------------------------------------------------------------ composición
off = int(SHIFT * K)
ink, paper = ink[:, off:off + N], paper[:, off:off + N]
Y, X = np.mgrid[0:N, 0:N].astype(np.float32) / K
COLORS = {"amarillo": (241, 176, 22), "azul": (128, 166, 208)}   # azul: pecho del tucán de páramo
import sys
COLOR = sys.argv[1] if len(sys.argv) > 1 else "azul"
if COLOR != "azul":
    OUT = OUT.with_name(f"icon_{COLOR}.png")
base_col = np.array(COLORS[COLOR], np.float32) / 255
cream = np.array([247, 241, 226], np.float32) / 255
black = np.array([20, 18, 16], np.float32) / 255
vig = np.clip(np.hypot(X - 520, Y - 450) / 780, 0, 1) ** 2
bg = base_col[None, None] * (1 - 0.20 * vig[..., None])
shadow = blur(paper, 22)
sy, sx = int(14 * K), int(10 * K)
shadow = np.pad(shadow, ((sy, 0), (0, sx)))[:N, sx:]
bg = bg * (1 - 0.16 * shadow[..., None])
img = bg * (1 - paper[..., None]) + cream[None, None] * paper[..., None]
img = img * (1 - ink[..., None]) + black[None, None] * ink[..., None]

R = 228
qx = np.clip(np.maximum(R - X, X - (1024 - R)), 0, None)
qy = np.clip(np.maximum(R - Y, Y - (1024 - R)), 0, None)
alpha = (np.hypot(qx, qy) <= R).astype(np.float32)

rgba = np.dstack([img, alpha]).reshape(1024, 2, 1024, 2, 4).mean(axis=(1, 3))
raw = (np.clip(rgba, 0, 1) * 255).round().astype(np.uint8).tobytes()
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1024x1024", "-i", "-",
                str(OUT)], input=raw, check=True)
print("listo:", OUT)
