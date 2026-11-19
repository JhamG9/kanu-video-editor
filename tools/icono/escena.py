"""Ilustración de la pantalla de carga: el tucán de Kanu de cuerpo completo, parado en la rama de un árbol,
con montañas y palmas de cera de fondo. Misma técnica de grabado a plumilla que el icono.

Solo usa numpy y ffmpeg. Lienzo vertical de 1024 × 1184 (el panel derecho del splash).
    python3 tools/icono/escena.py               -> apps/legacy-ui/splash.png (variante D: páramo, la elegida)
    python3 tools/icono/escena.py todas CARPETA -> CARPETA/opcion_A.png, _B, _C (para elegir)
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tucan_cuerpo import render as render_tucan  # noqa: E402

OUT = HERE.parents[1] / "apps" / "legacy-ui" / "splash.png"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
SW, SH, K = 1024, 1184, 2
Y, X = np.mgrid[0:SH * K, 0:SW * K].astype(np.float32) / K
BLUE = np.array([128, 166, 208], np.float32) / 255
CREAM = np.array([247, 241, 226], np.float32) / 255
BLACK = np.array([20, 18, 16], np.float32) / 255


# ------------------------------------------------------------------ herramientas de grabado
def noise(scale, seed):
    g = np.random.default_rng(seed).random((int(SH / scale) + 3, int(SW / scale) + 3)).astype(np.float32)
    gx, gy = np.clip(X, 0, SW - 1) / scale, np.clip(Y, 0, SH - 1) / scale
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


def smooth(v, w):
    k = np.ones(int(w * K)) / int(w * K)
    return np.convolve(np.pad(v, len(k), mode="edge"), k, mode="same")[len(k):-len(k)]


def ink_col(haze):
    """Tinta que se aclara hacia el azul con la distancia (perspectiva aérea)."""
    return BLACK * (1 - haze) + BLUE * 0.82 * haze


def curve(pts, n=200, soft=0):
    pts = np.array(pts, float)
    for _ in range(soft):                                    # esquinas suaves (Chaikin)
        q = np.empty((2 * len(pts) - 2, 2))
        q[0::2] = 0.75 * pts[:-1] + 0.25 * pts[1:]
        q[1::2] = 0.25 * pts[:-1] + 0.75 * pts[1:]
        pts = np.vstack([pts[:1], q, pts[-1:]])
    t = np.linspace(0, 1, n)
    tt = np.linspace(0, 1, len(pts))
    return np.array([np.interp(t, tt, pts[:, k]) for k in (0, 1)]).T


def box(x0, y0, r):
    return (slice(max(0, int((y0 - r) * K)), max(0, int((y0 + r) * K))),
            slice(max(0, int((x0 - r) * K)), max(0, int((x0 + r) * K))))


def tube_mask(pts, w):
    seg = curve(pts, max(12, len(pts) * 3))
    m = np.zeros_like(X)
    for x0, y0 in seg:
        sl = box(x0, y0, w + 2)
        m[sl] = np.maximum(m[sl], (np.hypot(X[sl] - x0, Y[sl] - y0) < w).astype(np.float32))
    return m


class Scene:
    def __init__(self):
        sky_t = np.clip(Y / 620, 0, 1)
        self.img = np.empty((SH * K, SW * K, 3), np.float32)
        self.img[:] = BLUE * (1.04 - 0.10 * (1 - sky_t[..., None]) ** 2)
        self.paint(lines(Y, 5.6, 0.11 * (1 - sky_t) ** 1.5 + 0.015) * (Y < 700), ink_col(0.72))

    def paint(self, mask, color, amount=1.0):
        a = np.clip(mask * amount, 0, 1)[..., None]
        self.img = self.img * (1 - a) + np.asarray(color, np.float32) * a

    # ---------------------------------------------------------- cielo
    def sun(self, cx, cy, r):
        d = np.hypot(X - cx, Y - cy)
        disc = (d < r).astype(np.float32)
        self.paint(disc, CREAM, 0.95)
        self.paint(disc * lines(d, 5.0, 0.12 + 0.25 * (d / r) ** 3), ink_col(0.45))
        self.paint(edge(disc, 1.2), ink_col(0.4))
        rays = lines(np.degrees(np.arctan2(Y - cy, X - cx)) * 3, 18, 0.18) * (d > r + 8) * (d < r + 40 + 30 * noise(20, 3))
        self.paint(rays, ink_col(0.62))

    def cumulus(self, puffs, base):
        m = np.zeros_like(X)
        for cx, cy, r in puffs:
            m = np.maximum(m, (np.hypot(X - cx, Y - cy) < r).astype(np.float32))
        m *= (Y < base)
        self.paint(m, CREAM, 0.95)
        under = np.clip((Y - (base - 40)) / 40, 0, 1)
        self.paint(m * lines(Y, 4.4, 0.06 + 0.55 * under ** 1.5), ink_col(0.3))
        self.paint(edge(m, 1.2), ink_col(0.25))

    # ---------------------------------------------------------- montañas
    @staticmethod
    def ridge(x, base, peaks, rough, seed):
        y = np.full_like(x, base, dtype=np.float32)
        for c, h, w in peaks:
            y -= h * np.exp(-np.abs(x - c) / w)
        return y - rough * (noise1(x, 40, seed) - 0.5) - rough * 0.5 * (noise1(x, 13, seed + 1) - 0.5)

    def mountains(self, ranges):
        self.ranges = ranges
        for i, rg in enumerate(ranges):
            base, peaks, rough, haze, t0 = rg[:5]
            snow_d = rg[5] if len(rg) > 5 else (50 if i == 0 else 0)
            ry = self.ridge(X[0], base, peaks, rough, 20 + i)
            R, Rs = ry[None, :], smooth(ry, 14)[None, :]
            mask = (Y > R).astype(np.float32)
            slope = smooth(np.gradient(smooth(ry, 30)) * K, 50)[None, :]
            shade = np.clip(slope * 1.4, 0, 1)
            depth = np.clip((Y - R) / 150, 0, 1)
            snow = (snow_d > 0) * np.clip(1 - (Y - R) / (max(snow_d, 1) * (0.5 + 0.8 * noise(26, 60 + i))), 0, 1) * (R < base - 110)
            self.paint(mask, BLUE * (0.99 - 0.035 * i))
            self.paint(mask * (snow > 0.05), CREAM, 0.9)
            tone = (t0 + 0.42 * shade * (1 - 0.75 * depth)) * (1 - 0.55 * depth * (i < len(ranges) - 1)) + 0.05 * (noise(22, 40 + i) - 0.5)
            contour = lines(Y - Rs, 4.8, tone * (1 - 0.6 * snow))
            hatch = lines(proj(58), 4.2, (shade - 0.25) * 0.9 * (1 - depth)) * (1 - snow)
            self.paint(mask * np.maximum(contour, hatch), ink_col(haze))
            self.paint(edge(mask, 1.2 + 0.3 * i), ink_col(haze * 0.75))

    def ridge_y(self, i, x):
        base, peaks, rough = self.ranges[i][:3]
        return float(self.ridge(np.array([x], np.float32), base, peaks, rough, 20 + i)[0])

    def river(self, pts, w_far, w_near):
        seg = curve(pts, 500, soft=4)
        m = np.zeros_like(X)
        for (x0, y0), t in zip(seg, np.linspace(0, 1, len(seg))):
            w = w_far + (w_near - w_far) * t
            sl = box(x0, y0, w + 4)
            m[sl] = np.maximum(m[sl], ((np.abs(X[sl] - x0) < w) & (np.abs(Y[sl] - y0) < 3)).astype(np.float32))
        m = np.clip(blur(m, 2) * 3, 0, 1)
        self.paint(m, CREAM, 0.9)
        self.paint(m * lines(Y + 2 * np.sin(X / 13), 4.0, 0.18 + 0.2 * noise(10, 5)), ink_col(0.4))
        self.paint(edge(m, 1.2), ink_col(0.35))

    # ---------------------------------------------------------- vegetación
    def wax_palm(self, bx, by, h, lean, haze, seed):
        t = np.clip((by - Y) / h, 0, 1)
        cx = bx + lean * t ** 2 * h * 0.12
        w = 3.4 - 1.2 * t
        trunk = ((np.abs(X - cx) < w) & (Y < by) & (Y > by - h)).astype(np.float32)
        self.paint(trunk * np.maximum(lines(Y + 0.3 * X, 7.0, 0.45), (np.abs(X - cx) > w * 0.25).astype(np.float32)),
                   ink_col(haze))
        top = (bx + lean * h * 0.12, by - h)
        r = np.random.default_rng(seed)
        crown = np.zeros_like(X)
        sc = h / 320
        for k in range(14):
            a = -np.pi / 2 + (k - 6.5) / 6.5 * 2.4 + r.normal(0, 0.08)
            L = (70 + 28 * r.random()) * sc
            s = np.linspace(0, 1, 46)
            px = top[0] + np.cos(a) * L * s
            py = top[1] + np.sin(a) * L * s + 46 * sc * s ** 2 * (1 + abs(np.cos(a)))
            for j in range(0, 46, 2):
                sl = box(px[j], py[j], 16)
                xx, yy = X[sl], Y[sl]
                crown[sl] = np.maximum(crown[sl], (np.hypot(xx - px[j], yy - py[j]) < (2.6 * (1 - s[j]) + 1.0) * max(sc, 0.6)).astype(np.float32))
                if 6 < j < 42:
                    crown[sl] = np.maximum(crown[sl], ((np.abs((xx - px[j]) * np.sin(a) - (yy - py[j]) * np.cos(a)) < 0.8)
                                                       & (np.hypot(xx - px[j], yy - py[j]) < (13 * (1 - s[j]) + 3) * sc)).astype(np.float32))
        self.paint(crown, ink_col(haze))

    def canopy(self, blobs, haze, t0, seed, cs=26.0):
        """Copa de grabado: muchas matas redondas, cada una con luz arriba a la izquierda y sombra abajo."""
        r = np.random.default_rng(seed)
        xs = np.array([b[0] for b in blobs]); ys = np.array([b[1] for b in blobs]); rs = np.array([b[2] for b in blobs])
        pts = []
        for cx, cy, rr in blobs:
            for _ in range(int((rr / cs) ** 2 * 1.6) + 3):
                a, d = r.random() * 2 * np.pi, rr * np.sqrt(r.random()) * 0.95
                pts.append((cx + np.cos(a) * d, cy + np.sin(a) * d, cs * (0.75 + 0.5 * r.random())))
        pts.sort(key=lambda p: p[1] + 0.4 * p[0])
        gx0, gy0 = xs.min() - rs.max(), ys.min() - rs.max()
        ca, sa = np.cos(np.radians(-35)), np.sin(np.radians(-35))
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
            side = np.clip(((xx - cx) * 0.6 + (yy - cy) * 0.8) / rr, -1, 1)
            gl = np.clip(1.05 - ((xx - gx0) / 500 + (yy - gy0) / 650), 0, 1)
            tone = t0 + 0.38 * side + 0.25 * (1 - gl) - 0.12
            ln = lines(xx * ca + yy * sa + 4 * np.sin((yy + xx) / 9), 4.4, tone)
            rim = ((d > rad - 1.6) & (d < rad) & (side > -0.2)).astype(np.float32)
            sub = self.img[y0:y1, x0:x1]
            base = BLUE * (0.95 - 0.06 * np.clip(side, 0, 1)[..., None])
            sub[:] = sub * (1 - mk[..., None]) + base * mk[..., None]
            a = np.clip(np.maximum(ln, rim) * mk, 0, 1)[..., None]
            sub[:] = sub * (1 - a) + ink_col(haze) * a

    def forest_line(self, i, haze, step=44, seed=1):
        rng = np.random.default_rng(seed)
        for cx in range(-20, 1060, step):
            if rng.random() < 0.7:
                yb = self.ridge_y(i, cx)
                r0 = 16 + 10 * rng.random()
                self.canopy([(cx, yb + 8, r0), (cx + 16, yb + 12, r0 * 0.8)], haze, 0.40, int(cx) + 100 + seed, cs=10.0)

    def wood(self, pts, w0, w1, haze=0.0, skip=None):
        """Tronco o rama: corteza con líneas a lo largo, más oscura del lado de abajo."""
        seg = curve(pts, 220)
        tt = np.linspace(0, 1, len(seg))
        m = np.zeros_like(X)
        d = np.full_like(X, 1e9)
        side = np.zeros_like(X)
        along = np.zeros_like(X)
        for i in range(len(seg) - 1):
            (x0, y0), (x1, y1) = seg[i], seg[i + 1]
            w = w0 + (w1 - w0) * tt[i]
            sl = box(x0, y0, w + 6)
            xx, yy = X[sl], Y[sl]
            dd = np.hypot(xx - x0, yy - y0)
            m[sl] = np.maximum(m[sl], (dd < w).astype(np.float32))
            closer = dd < d[sl]
            nx, ny = -(y1 - y0), (x1 - x0)
            nn = np.hypot(nx, ny) + 1e-6
            side[sl] = np.where(closer, ((xx - x0) * nx + (yy - y0) * ny) / nn / w, side[sl])
            along[sl] = np.where(closer, tt[i] * np.hypot(*(seg[-1] - seg[0])), along[sl])
            d[sl] = np.where(closer, dd, d[sl])
        if skip is not None:
            m = m * (1 - skip)
        down = 1.0 if seg[-1][0] > seg[0][0] else -1.0      # ramas horizontales: la sombra va abajo
        if abs(seg[-1][0] - seg[0][0]) < abs(seg[-1][1] - seg[0][1]):
            down = -1.0                                       # troncos verticales: la sombra va a la derecha
        shadow = np.clip(side * down, 0, 1)
        tone = 0.16 + 0.66 * shadow ** 1.2 + 0.12 * (noise(9, 8) - 0.5)
        bark = lines(side * 30 + 4 * np.sin(along / 19) + 5 * noise(14, 11), 5.0, tone)
        cracks = lines(along + 8 * noise(7, 12), 34, 0.06) * (np.abs(side) < 0.7) * (noise(25, 4) > 0.55)
        self.paint(m, CREAM, 0.6)
        self.paint(m * np.maximum(bark, cracks), ink_col(haze))
        self.paint(edge(m, 1.8), ink_col(haze))
        return m

    def leaves(self, items, haze=0.0):
        """Hojas sueltas a plumilla: (x, y, largo, ángulo en grados)."""
        for it in items:
            cx, cy, L, ang = it[:4]
            wr = it[4] if len(it) > 4 else 0.24
            a = np.radians(ang)
            sl = box(cx, cy, L + 4)
            xx, yy = X[sl], Y[sl]
            u = (xx - cx) * np.cos(a) + (yy - cy) * np.sin(a)
            v = -(xx - cx) * np.sin(a) + (yy - cy) * np.cos(a)
            t = np.clip(u / L, 0, 1)
            half = L * wr * np.sin(np.pi * t) ** 0.8
            m = np.zeros_like(X)
            m[sl] = ((u > 0) & (u < L) & (np.abs(v) < half)).astype(np.float32)
            vv = np.zeros_like(X); vv[sl] = v
            uu = np.zeros_like(X); uu[sl] = u
            self.paint(m, CREAM, 0.92)
            self.paint(m * lines(uu - np.abs(vv) * 0.9, 4.2, 0.22 + 0.5 * (vv > 0)), ink_col(haze))
            self.paint(m * (np.abs(vv) < 0.9), ink_col(haze))
            self.paint(edge(m, 1.3), ink_col(haze))

    # ---------------------------------------------------------- páramo
    def frailejon(self, x, yb, h, haze, seed):
        """Frailejón: tallo grueso, falda de hojas secas colgando y roseta de hojas largas y afelpadas."""
        r = np.random.default_rng(seed)
        w = max(2.2, h * 0.10)
        top = yb - h * 0.64
        skirt_h = h * 0.26
        sl = box(x, yb - h / 2, h * 0.8 + 6)
        xx, yy = X[sl], Y[sl]
        trunk = ((np.abs(xx - x) < w) & (yy < yb) & (yy > top)).astype(np.float32)
        skirt = ((np.abs(xx - x) < w * (1.55 - 0.4 * (yy - top) / skirt_h)) & (yy > top) & (yy < top + skirt_h)).astype(np.float32)
        body = np.maximum(trunk, skirt)
        sc = max(h / 120, 0.35)
        shade = np.clip((xx - x) / (w * 1.4), -1, 1)
        hang = lines(xx + 2.2 * np.sin(yy / (4 * sc)), 3.0 * sc, 0.55 + 0.3 * shade) * \
            (((yy - top) / (5 * sc) + r.random() * 5 + np.floor((xx - x) / (3 * sc)) * 0.37) % 1.0 > 0.18)
        bark = lines(yy + 0.9 * np.abs(xx - x), 3.4 * sc, 0.40 + 0.35 * shade)
        tex = np.where(yy < top + skirt_h, hang, bark)
        m = np.zeros_like(X); m[sl] = body
        t = np.zeros_like(X); t[sl] = tex
        self.paint(m, BLUE * 0.82)
        self.paint(m * t, ink_col(haze))
        self.paint(edge(m, 1.0 + 0.4 * (h > 80)), ink_col(haze))
        if h < 46:                                              # lejos: la roseta es un penacho claro
            d = np.hypot((X - x) / (h * 0.28), (Y - top + h * 0.06) / (h * 0.16))
            cr = (d < 1).astype(np.float32)
            self.paint(cr, CREAM, 0.9 - 0.5 * haze)
            self.paint(cr * lines(X + 0.4 * np.abs(Y - top), 2.0, 0.25 + 0.35 * (X > x)), ink_col(haze))
            return
        L = h * 0.40
        items = []
        for k in range(22):                                     # roseta: casi todas hacia arriba, algunas abiertas
            u = (k + r.random() * 0.6) / 22 * 2 - 1
            a = -90 + 78 * np.sign(u) * abs(u) ** 1.25
            items.append((x + r.normal(0, w * 0.25), top + 2 + r.normal(0, 1.5), L * (0.7 + 0.45 * r.random()), a, 0.14))
        items.sort(key=lambda it: -abs(it[3] + 90))            # las abiertas atrás, las de arriba adelante
        self.leaves(items, haze)
        for k in range(int(r.integers(1, 4))):                  # tallos florales con capítulos
            ang = np.radians(-90 + r.normal(0, 22))
            ln = L * (1.0 + 0.5 * r.random())
            fx, fy = x + np.cos(ang) * ln, top + np.sin(ang) * ln
            self.paint(tube_mask([(x, top), ((x + fx) / 2 + r.normal(0, 4), (top + fy) / 2), (fx, fy)], max(0.8, h * 0.008)),
                       ink_col(haze))
            for j in range(3):
                d = np.hypot(X - fx - (j - 1) * h * 0.035, Y - fy - abs(j - 1) * h * 0.02)
                fl = (d < max(2.2, h * 0.026)).astype(np.float32)
                self.paint(fl, CREAM)
                self.paint(fl * lines(np.arctan2(Y - fy, X - fx) * 8, 1.0, 0.3), ink_col(haze))
                self.paint(edge(fl, 0.9), ink_col(haze))

    def tuft(self, x, yb, h, haze, seed):
        """Macolla de pajonal: hojas finas que salen de la base y se doblan."""
        r = np.random.default_rng(seed)
        m = np.zeros_like(X)
        for _ in range(int(9 + h / 6)):
            a = np.radians(-90 + r.normal(0, 28))
            L = h * (0.6 + 0.5 * r.random())
            bend = r.normal(0, 0.5)
            pts = [(x + r.normal(0, h * 0.06) + np.cos(a) * L * t + bend * L * 0.3 * t * t,
                    yb + np.sin(a) * L * t + L * 0.25 * t * t) for t in np.linspace(0, 1, 14)]
            m = np.maximum(m, tube_mask(pts, max(0.55, h * 0.009)))
        self.paint(m, ink_col(haze))

    def mist(self, y, h, amount=0.55):
        band = np.exp(-((Y - y) / h) ** 2) * (0.7 + 0.3 * noise(60, int(y)))
        self.paint(band, CREAM, amount)

    def lake(self, cx, cy, rx, ry):
        d = ((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2 * (1 + 0.15 * np.sin(X / 37))
        m = (d < 1).astype(np.float32)
        self.paint(m, CREAM, 0.85)
        self.paint(m * lines(Y, 3.6, 0.10 + 0.35 * np.clip(d, 0, 1)), ink_col(0.4))
        self.paint(edge(m, 1.2), ink_col(0.35))

    # ---------------------------------------------------------- tucán
    def toucan(self, T, scale, feet_x, branch_top, mirror=False, chest=None):
        """Pinta el tucán y guarda la máscara de sus dedos (se repintan sobre la rama)."""
        ink, paper, feet, ch, TK = T["ink"], T["paper"], T["feet"], T["chest"], T["K"]
        if mirror:
            ink, paper, feet, ch = ink[:, ::-1], paper[:, ::-1], feet[:, ::-1], ch[:, ::-1]
        Wt = ink.shape[1] / TK
        fx_t = 560 if not mirror else Wt - 560
        ox, oy = feet_x - scale * fx_t, branch_top - scale * T["branch_y"]
        ix, iy = (X - ox) / scale * TK, (Y - oy) / scale * TK
        ok = (ix >= 0) & (iy >= 0) & (ix < ink.shape[1] - 1) & (iy < ink.shape[0] - 1)
        ixc, iyc = np.clip(ix, 0, ink.shape[1] - 2), np.clip(iy, 0, ink.shape[0] - 2)
        i0, j0 = ixc.astype(int), iyc.astype(int)
        fx, fy = ixc - i0, iyc - j0

        def sample(a):
            return ok * (a[j0, i0] * (1 - fx) * (1 - fy) + a[j0, i0 + 1] * fx * (1 - fy)
                         + a[j0 + 1, i0] * (1 - fx) * fy + a[j0 + 1, i0 + 1] * fx * fy)

        p, k, f = sample(paper), sample(ink), sample(feet)
        sh = blur(p, 14)
        sh = np.roll(np.pad(sh, ((10 * K, 0), (0, 0)))[:SH * K], (8 if not mirror else -8) * K, axis=1)
        self.img *= (1 - 0.28 * sh[..., None])
        self.paint(p, CREAM)
        if chest is not None:                                   # tucán de páramo: pecho azul grisáceo
            self.paint(sample(ch), chest)
        self.paint(k, BLACK)
        self.feet = np.clip(f * 1.3, 0, 1)
        self.feet_ink = k * self.feet

    def grip(self):
        """Los dedos del tucán van encima de la rama."""
        self.paint(self.feet, CREAM)
        self.paint(self.feet_ink, BLACK)

    def save(self, out):
        o = self.img.reshape(SH, K, SW, K, 3).mean(axis=(1, 3))
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{SW}x{SH}", "-i", "-",
                        str(out)], input=(np.clip(o, 0, 1) * 255).round().astype(np.uint8).tobytes(), check=True)
        print("listo:", out)


ANDES = [
    (470, [(120, 150, 90), (380, 210, 120), (660, 120, 80), (900, 190, 110)], 22, 0.66, 0.16),
    (575, [(40, 120, 100), (260, 160, 110), (560, 105, 120), (800, 150, 90), (1010, 90, 70)], 18, 0.46, 0.24),
    (700, [(150, 70, 200), (520, 50, 200), (880, 80, 180)], 10, 0.30, 0.30),
]


def variant_A(T):
    """Rama al frente: el tucán en una rama que sale del árbol de la izquierda; Andes y palmas detrás."""
    s = Scene()
    s.cumulus([(150, 150, 34), (200, 128, 46), (258, 140, 38), (305, 156, 26)], 172)
    s.cumulus([(700, 210, 30), (750, 188, 42), (805, 202, 34), (848, 216, 22)], 230)
    s.mountains(ANDES)
    s.forest_line(2, 0.36)
    s.wax_palm(338, 704, 310, 0.8, 0.26, 1)
    s.wax_palm(985, 696, 300, -0.5, 0.28, 3)
    s.canopy([(900, 1080, 120), (1010, 1030, 120), (820, 1150, 110)], 0.10, 0.42, 300, cs=30.0)
    s.wood([(112, 1230), (124, 1000), (104, 840), (134, 600)], 30, 18)
    s.canopy([(10, 420, 150), (140, 350, 130), (250, 430, 100), (30, 610, 150), (190, 560, 110), (-20, 780, 130)],
             0.0, 0.42, 500, cs=34.0)
    top = 842
    s.toucan(T, 0.60, 600, top)                         # el tucán primero: la cola queda detrás de la rama
    s.wood([(118, 884), (420, top + 22), (700, top + 14), (940, top - 8)], 22, 9, skip=s.feet)
    s.grip()
    s.leaves([(915, top - 14, 58, -40), (925, top - 6, 50, 15), (880, top + 4, 44, 60), (250, top + 34, 52, 115)])
    return s


def variant_B(T):
    """Entre el follaje: más cerca, rama en diagonal y hojas que enmarcan arriba."""
    s = Scene()
    s.cumulus([(560, 160, 30), (606, 138, 42), (660, 154, 32)], 180)
    s.mountains([(520, [(260, 170, 110), (620, 150, 100), (900, 120, 90)], 20, 0.62, 0.18),
                 (640, [(120, 100, 140), (480, 80, 150), (820, 110, 120)], 14, 0.42, 0.26)])
    s.forest_line(1, 0.34, step=38, seed=7)
    s.wax_palm(150, 700, 330, 0.9, 0.24, 5)
    s.wax_palm(1000, 690, 280, -0.6, 0.28, 6)
    top = 902
    s.toucan(T, 0.78, 540, top)
    s.wood([(-20, 1004), (300, top + 34), (620, top + 18), (1060, top - 40)], 30, 16, skip=s.feet)
    s.grip()
    s.leaves([(70, 960, 70, 200), (110, 992, 64, 150), (985, top - 56, 66, -50), (1000, top - 32, 60, 20)])
    s.canopy([(-30, -10, 170), (110, 30, 120), (20, 170, 120), (210, -30, 110)], 0.0, 0.44, 610, cs=30.0)
    s.canopy([(1060, -20, 170), (930, 20, 120), (1040, 170, 120)], 0.0, 0.44, 620, cs=30.0)
    return s


def variant_C(T):
    """El valle: tucán más pequeño mirando hacia adentro, río entre montañas y sol."""
    s = Scene()
    s.sun(250, 230, 58)
    s.cumulus([(180, 270, 30), (226, 252, 40), (280, 268, 30)], 290)
    s.cumulus([(600, 140, 26), (640, 124, 36), (690, 138, 28)], 156)
    s.mountains([(500, [(90, 160, 100), (330, 120, 90), (560, 200, 120), (820, 150, 100)], 22, 0.66, 0.16),
                 (600, [(10, 110, 120), (240, 80, 120), (470, 120, 110), (720, 90, 120)], 16, 0.46, 0.24),
                 (720, [(120, 60, 200), (520, 40, 200)], 10, 0.30, 0.30)])
    s.river([(420, 640), (380, 700), (300, 770), (330, 880), (220, 1000), (120, 1190)], 6, 70)
    s.forest_line(2, 0.36, step=40, seed=9)
    for bx, by, h, seed in ((110, 760, 210, 11), (190, 772, 180, 12), (560, 730, 230, 13), (640, 740, 190, 14)):
        s.wax_palm(bx, by, h, 0.6, 0.30, seed)
    s.canopy([(60, 1080, 120), (180, 1130, 110), (-20, 980, 110)], 0.1, 0.42, 700, cs=28.0)
    s.wood([(930, 1230), (915, 1000), (940, 800), (905, 560)], 32, 20)
    top = 790
    s.toucan(T, 0.52, 640, top, mirror=True)
    s.wood([(930, 852), (760, top + 18), (560, top + 14), (410, top - 6)], 20, 8, skip=s.feet)
    s.grip()
    s.leaves([(410, top - 8, 50, 200), (420, top - 2, 46, 150), (460, top + 10, 40, 110)])
    s.canopy([(1050, 380, 160), (950, 290, 120), (1040, 560, 140), (1000, 700, 110)],
             0.0, 0.42, 720, cs=34.0)
    return s


CHEST = np.array([96, 128, 168], np.float32) / 255           # azul pizarra del tucán de páramo


def paramo(T, chest=None, lake=False):
    """Páramo: nevados al fondo, lomas con frailejones, pajonal y el tucán en la rama de un colorado (polylepis)."""
    s = Scene()
    s.cumulus([(620, 120, 26), (664, 100, 38), (716, 116, 28)], 136)
    s.mountains([(520, [(250, 300, 150), (720, 250, 130), (980, 160, 110)], 18, 0.62, 0.14, 150),
                 (640, [(80, 90, 220), (520, 70, 260), (900, 80, 220)], 10, 0.42, 0.20),
                 (760, [(300, 50, 300), (820, 40, 260)], 8, 0.24, 0.26)])
    s.mist(600, 30, 0.32)
    rng = np.random.default_rng(31)
    if lake:
        s.lake(560, 742, 230, 34)
    for i, (y0, y1, hmin, hmax, haze, n) in enumerate([(650, 720, 16, 30, 0.42, 26), (735, 860, 34, 70, 0.26, 16)]):
        pts = sorted(((rng.uniform(-20, 1040), rng.uniform(y0, y1)) for _ in range(n)), key=lambda p: p[1])
        for x, y in pts:
            if lake and ((x - 560) / 250) ** 2 + ((y - 742) / 50) ** 2 < 1:
                continue
            h = hmin + (hmax - hmin) * (y - y0) / (y1 - y0)
            s.frailejon(x, y, h, haze, int(x * 7 + y))
    for _ in range(40):
        x, y = rng.uniform(-20, 1040), rng.uniform(760, 1000)
        s.tuft(x, y, 14 + (y - 760) * 0.12, 0.38, int(x + y * 3))
    s.frailejon(930, 1190, 250, 0.0, 77)                     # frailejones grandes en primer plano
    s.frailejon(840, 1210, 190, 0.0, 78)
    s.wood([(96, 1240), (130, 1060), (88, 900), (150, 740), (118, 600)], 30, 17)
    s.canopy([(10, 450, 130), (130, 400, 110), (230, 470, 80), (40, 620, 120), (170, 590, 90), (-20, 760, 110)],
             0.0, 0.40, 900, cs=24.0)
    top = 846
    s.toucan(T, 0.60, 590, top, chest=chest)
    s.wood([(122, 900), (300, top + 34), (520, top + 16), (760, top + 6), (930, top - 18)], 22, 8, skip=s.feet)
    s.grip()
    s.leaves([(905, top - 26, 40, -40), (915, top - 20, 36, 10), (880, top - 10, 32, 60), (300, top + 40, 36, 120)])
    for _ in range(26):                                      # pajonal en primer plano
        x = rng.uniform(-30, 1060)
        y = rng.uniform(1080, 1200)
        s.tuft(x, y, 50 + rng.uniform(0, 40), 0.08, int(x * 3 + y))
    return s


def variant_D(T):
    return paramo(T)


def variant_E(T):
    return paramo(T, chest=CHEST)


def variant_F(T):
    return paramo(T, chest=CHEST, lake=True)


VARIANTS = {"A": variant_A, "B": variant_B, "C": variant_C, "D": variant_D, "E": variant_E, "F": variant_F}


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "D"           # D: páramo, pecho crema (la del splash)
    T = render_tucan()
    if which in ("todas", "paramo"):
        folder = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE
        for name, fn in VARIANTS.items():
            if which == "todas" or name in "DEF":
                fn(T).save(folder / f"opcion_{name}.png")
    else:
        VARIANTS[which](T).save(OUT)
