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

COLOR_KEYS = list(DEFAULTS.keys())


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
