"""Motor de color: una sola fórmula para la vista previa y para la exportación.

Los ajustes se convierten en una LUT 3D. El navegador usa esa LUT para la vista
previa (WebGL) y ffmpeg usa exactamente la misma para exportar (lut3d).
"""
import numpy as np

LUT_SIZE = 33

DEFAULTS = {
    "exposure": 0.0,     # EV, -2..2
    "contrast": 0,       # -100..100
    "highlights": 0,
    "shadows": 0,
    "whites": 0,
    "blacks": 0,
    "temperature": 0,    # + = más cálido
    "tint": 0,           # + = magenta, - = verde
    "vibrance": 0,
    "saturation": 0,
}

# Ajustes por color (HSL, como el mezclador de Lightroom): 8 gamas × tono / saturación / luminancia.
# Cada gama tiene su centro de tono en grados; entre dos centros se reparte suavemente.
HSL_COLORS = {"red": 0, "orange": 30, "yellow": 60, "green": 120, "aqua": 180, "blue": 225,
              "purple": 270, "magenta": 315}
for _c in HSL_COLORS:
    for _p in ("h", "s", "l"):
        DEFAULTS[f"hsl_{_c}_{_p}"] = 0       # -100..100
# Color por zonas (sombras / medios / luces): tono 0..360 y cuánto se tiñe 0..100.
ZONES = ("shadows", "mid", "high")
for _z in ZONES:
    DEFAULTS[f"zone_{_z}_hue"] = 0
    DEFAULTS[f"zone_{_z}_sat"] = 0

COLOR_KEYS = list(DEFAULTS.keys())
HSL_KEYS = [k for k in COLOR_KEYS if k.startswith("hsl_")]
ZONE_KEYS = [k for k in COLOR_KEYS if k.startswith("zone_")]


def color_settings(settings):
    out = dict(DEFAULTS)
    for k in COLOR_KEYS:
        if k in settings and settings[k] is not None:
            out[k] = float(settings[k])
    return out


def apply(rgb, s):
    """rgb: array (...,3) en 0..1 (codificado Rec.709). Devuelve el mismo formato."""
    s = color_settings(s)
    rgb = np.clip(rgb.astype(np.float64), 0.0, 1.0)

    # 1) Balance de blancos y exposición en luz lineal
    lin = rgb ** 2.2
    t = s["temperature"] / 100.0
    m = s["tint"] / 100.0
    gains = np.array([np.exp(0.12 * t), np.exp(-0.08 * m), np.exp(-0.12 * t)])
    gains /= 0.2126 * gains[0] + 0.7152 * gains[1] + 0.0722 * gains[2]
    lin = lin * gains * (2.0 ** s["exposure"])
    rgb = np.clip(lin, 0.0, None) ** (1 / 2.2)

    # 2) Curva de tonos sobre la luminancia
    Y = rgb @ np.array([0.2126, 0.7152, 0.0722])
    Yc = np.clip(Y, 0.0, 1.0)
    d = (s["contrast"] / 100.0 * 0.45) * (Yc - 0.5) * 4 * Yc * (1 - Yc)
    d += 0.25 * s["shadows"] / 100.0 * 6.75 * Yc * (1 - Yc) ** 2
    d += 0.25 * s["highlights"] / 100.0 * 6.75 * Yc ** 2 * (1 - Yc)
    d += 0.15 * s["whites"] / 100.0 * Yc ** 3
    d += 0.12 * s["blacks"] / 100.0 * (1 - Yc) ** 3
    rgb = rgb + d[..., None]

    # 3) Saturación e intensidad (vibrance: sube más lo que está apagado)
    Y2 = rgb @ np.array([0.2126, 0.7152, 0.0722])
    chroma = np.clip(rgb.max(axis=-1) - rgb.min(axis=-1), 0, 1)
    f = (1 + s["saturation"] / 100.0) * (1 + 0.7 * s["vibrance"] / 100.0 * (1 - np.clip(chroma * 2.2, 0, 1)))
    rgb = Y2[..., None] + (rgb - Y2[..., None]) * f[..., None]
    rgb = np.clip(rgb, 0.0, 1.0)

    # 4) Por color (HSL) y 5) por zonas: solo si hay algo movido
    if any(s[k] for k in HSL_KEYS):
        rgb = _hsl(rgb, s)
    if any(s[f"zone_{z}_sat"] for z in ZONES):
        rgb = _zones(rgb, s)
    return rgb


def _rgb2hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    v = rgb.max(-1)
    c = v - rgb.min(-1)
    safe = np.where(c > 1e-9, c, 1.0)
    h = np.where(v == r, ((g - b) / safe) % 6, np.where(v == g, (b - r) / safe + 2, (r - g) / safe + 4)) * 60.0
    h = np.where(c > 1e-9, h, 0.0)
    s = np.where(v > 1e-9, c / np.where(v > 1e-9, v, 1.0), 0.0)
    return h, s, v


def _hsv2rgb(h, s, v):
    k = lambda n: (n + h / 60.0) % 6                                          # noqa: E731
    f = lambda n: v - v * s * np.clip(np.minimum(k(n), 4 - k(n)), 0, 1)        # noqa: E731
    return np.stack([f(5), f(3), f(1)], -1)


def hue_weights(h):
    """Peso (0..1) de cada gama de HSL_COLORS para cada tono h (grados). Suman 1."""
    cs = list(HSL_COLORS.values())
    n = len(cs)
    w = []
    for i, c in enumerate(cs):
        prev, nxt = cs[i - 1] - (360 if i == 0 else 0), cs[(i + 1) % n] + (360 if i == n - 1 else 0)
        d = (h - c + 180) % 360 - 180                                          # distancia con signo
        gap = np.where(d < 0, c - prev, nxt - c)
        w.append(np.clip(1 - np.abs(d) / gap, 0, 1))
    return np.stack(w, -1)


def _hsl(rgb, s):
    h, sat, v = _rgb2hsv(rgb)
    w = hue_weights(h)
    chroma = sat * v
    wc = np.clip((chroma - 0.02) / 0.10, 0, 1)                    # los grises no cambian
    get = lambda p: np.array([s[f"hsl_{c}_{p}"] for c in HSL_COLORS]) / 100.0   # noqa: E731
    dh = (w @ get("h")) * 30.0 * wc                                 # hasta ±30° hacia la gama vecina
    ds = (w @ get("s")) * wc
    dl = (w @ get("l")) * wc
    sat = np.clip(sat * (1 + ds), 0, 1)
    out = _hsv2rgb((h + dh) % 360, sat, v)
    out = out * (2.0 ** (0.9 * dl))[..., None]                      # luminancia de ese color
    return np.clip(out, 0.0, 1.0)


def _zones(rgb, s):
    Y = np.clip(rgb @ np.array([0.2126, 0.7152, 0.0722]), 0, 1)
    ws = {"shadows": (1 - Y) ** 2, "mid": 2 * Y * (1 - Y), "high": Y ** 2}
    for z in ZONES:
        a = s[f"zone_{z}_sat"] / 100.0
        if not a:
            continue
        tint = _hsv2rgb(np.array(s[f"zone_{z}_hue"] % 360), np.array(1.0), np.array(1.0))
        tint = tint - tint @ np.array([0.2126, 0.7152, 0.0722])    # solo color, sin cambiar la luz
        rgb = rgb + (ws[z] * a * 0.16)[..., None] * tint
    return np.clip(rgb, 0.0, 1.0)


STYLE_LUT = None   # LUT propia del usuario (estilo), se aplica después de la corrección de Kanu


def _sample_lut(L, rgb):
    """Interpolación trilineal en una LUT 3D [b][g][r]."""
    n = L.shape[0]
    x = np.clip(rgb, 0, 1) * (n - 1)
    i0 = np.floor(x).astype(int).clip(0, n - 2)
    f = x - i0
    r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
    fr, fg, fb = f[:, :1], f[:, 1:2], f[:, 2:3]
    out = 0
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                w = (fr if dr else 1 - fr) * (fg if dg else 1 - fg) * (fb if db else 1 - fb)
                out = out + w * L[b0 + db, g0 + dg, r0 + dr]
    return np.clip(out, 0, 1)


def build_lut(settings, size=LUT_SIZE):
    """LUT con el rojo variando más rápido (orden .cube y de textura 3D)."""
    g = np.linspace(0, 1, size)
    b_, g_, r_ = np.meshgrid(g, g, g, indexing="ij")
    grid = np.stack([r_, g_, b_], axis=-1).reshape(-1, 3)
    out = apply(grid, settings)
    if STYLE_LUT is not None:
        out = _sample_lut(STYLE_LUT, out)
    return out


def lut_bytes(settings, size=LUT_SIZE):
    return (np.round(build_lut(settings, size) * 255)).astype(np.uint8).tobytes()


def write_cube(settings, path, size=LUT_SIZE):
    lut = build_lut(settings, size)
    with open(path, "w") as fh:
        fh.write("TITLE \"EditorVideo\"\n")
        fh.write(f"LUT_3D_SIZE {size}\n")
        fh.write("DOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n")
        for r, g, b in lut:
            fh.write(f"{r:.6f} {g:.6f} {b:.6f}\n")
    return path
