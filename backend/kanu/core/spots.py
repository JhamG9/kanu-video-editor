"""Manchas del sensor (polvo): medirlas y quitarlas sin inventar píxeles."""
from pathlib import Path

import numpy as np

from kanu import config
from kanu.infra import ffmpeg as ff


# ------------------------------------------------------------------ manchas del sensor (polvo)
# El polvo no tapa la imagen: la oscurece un poco, siempre en el mismo punto del sensor y con
# borde suave. Se mide cuánto oscurece (T, de 0 a 1) y se divide por T: no se inventan píxeles.
def _spot_crop_frames(path, meta, x, y, S, n=48):
    """Recortes de la zona en los fotogramas clave (rápido: no decodifica el resto)."""
    W, H = meta["width"], meta["height"]
    x0 = int(min(max(x - S // 2, 0), W - S)) // 2 * 2
    y0 = int(min(max(y - S // 2, 0), H - S)) // 2 * 2
    raw = ff.run([config.FFMPEG, "-v", "error", "-skip_frame", "nokey", "-i", str(path), "-vf",
               f"crop={S}:{S}:{x0}:{y0},format=gray16le", "-fps_mode", "vfr", "-f", "rawvideo", "-"]).stdout
    fr = np.frombuffer(raw, "<u2").reshape(-1, S, S) / 65535.0
    if len(fr) > n:
        fr = fr[np.linspace(0, len(fr) - 1, n).astype(int)]
    return fr, x0, y0


def _box(a, r):
    """Desenfoque rápido (3 cajas ≈ gaussiano de sigma ~ r)."""
    r = max(1, int(r))
    for _ in range(3):
        for ax in (0, 1):
            pad = [(r + 1, r), (0, 0)] if ax == 0 else [(0, 0), (r + 1, r)]
            c = np.cumsum(np.pad(a, pad, mode="edge"), axis=ax)
            a = ((c[2 * r + 1:] - c[:-2 * r - 1]) if ax == 0 else (c[:, 2 * r + 1:] - c[:, :-2 * r - 1])) / (2 * r + 1)
    return a


def _background(f, mask, r):
    """Imagen sin la zona de la mancha: se rellena por difusión desde el borde (respeta degradados)."""
    g = f.copy()
    g[mask] = np.median(f[~mask])
    for _ in range(25):
        g = _box(g, max(2, r / 5))
        g[~mask] = f[~mask]
    return _box(g, max(1.5, r / 10))


def _ratio(fr, cx, cy, r, yy, xx):
    """Cociente imagen / fondo sin mancha (mediana entre fotogramas: la escena se promedia, la mancha queda)."""
    mask = np.hypot(xx - cx, yy - cy) < r * 1.6
    return np.median(np.array([f / np.maximum(_background(f, mask, r), 1e-3) for f in fr]), 0)


def _fit_gauss(d, rr):
    """d ≈ a·exp(-(rr/s)²): mejor (error, a, s)."""
    best = None
    for ss in np.geomspace(2.0, max(4.0, rr.max() / 1.3), 36):
        g = np.exp(-(rr / ss) ** 2)
        aa = float(np.sum(d * g) / np.sum(g * g))
        e = float(np.sum((d - aa * g) ** 2))
        if best is None or e < best[0]:
            best = (e, aa, ss)
    return best


def measure_spot(path, meta, x, y, r=40):
    """Mide una mancha cerca de (x, y) en píxeles del original. r = radio aproximado (px).
    Devuelve {x, y, r, a, s, fit} (a = cuánto oscurece en el centro, s = tamaño, fit = qué tan
    redonda es la medida, 0..1) o None si ahí no hay una mancha de sensor."""
    r = float(min(max(r, 8), 300))
    S = min(int(max(192, 7 * r)) // 2 * 2, meta["height"] // 2 * 2)
    fr, x0, y0 = _spot_crop_frames(path, meta, x, y, S)
    if len(fr) < 4:
        return None
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    cx, cy = x - x0, y - y0
    # 1) centro aproximado: donde más oscurece (suavizado), cerca del clic
    d0 = 1 - _ratio(fr, cx, cy, r, yy, xx)
    sm = _box(d0, max(2, r / 6)) * (np.hypot(xx - cx, yy - cy) < r)
    cy, cx = np.unravel_index(int(np.argmax(sm)), sm.shape)
    cx, cy = float(cx), float(cy)
    # 2) con el fondo medido alrededor de ese centro, afinar centro (±4 px) y tamaño
    d = 1 - _ratio(fr, cx, cy, r, yy, xx)
    win = np.hypot(xx - cx, yy - cy) < r * 1.6
    best = None
    for dy in np.arange(-4, 4.5, 1.0):
        for dx in np.arange(-4, 4.5, 1.0):
            rr = np.hypot(xx[win] - cx - dx, yy[win] - cy - dy)
            e, aa, ss = _fit_gauss(d[win], rr)
            if best is None or e < best[0]:
                best = (e, aa, ss, cx + dx, cy + dy)
    e, a, s, cx, cy = best
    dv = d[win]
    fit = 1 - e / max(float(np.sum((dv - dv.mean()) ** 2)), 1e-9)       # R²: 1 = mancha redonda perfecta
    if a < 0.03 or fit < 0.5:
        return None
    return {"x": round(float(cx + x0), 1), "y": round(float(cy + y0), 1), "r": round(float(max(r * 0.5, 2.4 * s)), 1),
            "a": round(min(a, 0.9), 4), "s": round(float(s), 2), "fit": round(float(fit), 2)}


def spot_map(spot, out):
    """Imagen (gris 16 bits) con la transmisión T de la mancha, para dividir en ffmpeg."""
    C = int(np.ceil(spot["s"] * 3.2)) * 2 // 2 * 2 + 2
    yy, xx = np.mgrid[0:C, 0:C]
    x0, y0 = int(spot["x"] - C / 2) // 2 * 2, int(spot["y"] - C / 2) // 2 * 2
    rr = np.hypot(xx + x0 - spot["x"], yy + y0 - spot["y"])
    T = 1 - spot["a"] * np.exp(-(rr / spot["s"]) ** 2)
    ff.run([config.FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray16le", "-s", f"{C}x{C}", "-i", "-",
         str(out)], input=(np.clip(T, 0, 1) * 65535).round().astype("<u2").tobytes())
    return C, x0, y0


def spot_graph(spots, maps, meta, first_input=1):
    """Grafo de ffmpeg: corrige solo el recuadro de cada mancha y lo vuelve a poner encima."""
    W, H, pf = meta["width"], meta["height"], meta.get("pix_fmt", "yuv422p10le")
    n = len(spots)
    g = [f"[0:v]split={n + 1}[b0]" + "".join(f"[c{i}]" for i in range(n))]
    for i, (C, x0, y0) in enumerate(maps):
        x0, y0 = min(max(x0, 0), W - C), min(max(y0, 0), H - C)
        g.append(f"[c{i}]crop={C}:{C}:{x0}:{y0},format=gbrpf32le[cc{i}]")
        g.append(f"[{first_input + i}:v]format=gbrpf32le[m{i}]")
        g.append(f"[cc{i}][m{i}]blend=all_mode=divide,format={pf}[f{i}]")
        g.append(f"[b{i}][f{i}]overlay={x0}:{y0}:format=auto[b{i + 1}]")
    return ";".join(g), f"[b{n}]"


def clean_video(src, meta, spots, maps_dir, out):
    """Copia ProRes del original sin las manchas (se hace ANTES de estabilizar: la mancha está fija en el sensor)."""
    maps_dir = Path(maps_dir)
    maps_dir.mkdir(parents=True, exist_ok=True)
    inputs, maps = [], []
    for i, sp in enumerate(spots):
        p = maps_dir / f"mancha_{i}.png"
        maps.append(spot_map(sp, p))
        inputs += ["-i", str(p)]
    fc, last = spot_graph(spots, maps, meta)
    tmp = Path(out).with_name(Path(out).stem + ".parcial.mov")
    ff.run([config.FFMPEG, "-v", "error", "-y", "-i", str(src), *inputs, "-filter_complex", fc + f";{last}format=p210le[v]",
         "-map", "[v]", "-map", "0:a:0?", "-c:v", "prores_videotoolbox", "-profile:v", "hq",
         "-c:a", "pcm_s16le", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-r", meta["fps_raw"], str(tmp)])
    tmp.replace(out)
    return Path(out)
