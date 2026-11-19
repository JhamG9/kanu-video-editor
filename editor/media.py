"""Todo lo que toca ffmpeg: metadatos, fotogramas, análisis automático, ruido y exportación."""
import json
import math
import subprocess
from pathlib import Path

import numpy as np

import grade

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

# Conversión YUV Rec.709 (rango TV) -> RGB completo, igual en vista previa y exportación
TO_RGB = "scale={w}:{h}:flags=lanczos:in_color_matrix=bt709:in_range=tv:out_color_matrix=bt709:out_range=pc"


def knee(meta):
    """Recupera los superblancos (Sony graba hasta 1023 aunque el blanco legal es 940).

    Comprime suavemente lo que está por encima del ~75 % hasta el pico real del clip,
    para que el cielo conserve su detalle en vez de quedar recortado a blanco.
    """
    peak = meta.get("white_peak") or 0
    if peak <= 0.925:  # sin superblancos: no se toca nada
        return None
    W, K = 0.9189, 0.79  # blanco legal y comienzo de la compresión (fracción del máximo)
    s = (W - K) / (peak - K)
    return f"lutyuv=y='if(lt(val\\,{K}*maxval)\\,val\\,{K}*maxval+(val-{K}*maxval)*{s:.4f})'"


def to_rgb(meta, w, h):
    k = knee(meta)
    return (k + "," if k else "") + TO_RGB.format(w=w, h=h)

DENOISE = {
    "off": None,
    "suave": "hqdn3d=1.5:1.2:3:3",
    "media": "atadenoise=0a=0.02:0b=0.04:1a=0.02:1b=0.04:2a=0.02:2b=0.04:s=7,hqdn3d=2.5:2:5:4",
    "fuerte": "atadenoise=0a=0.03:0b=0.06:1a=0.03:1b=0.06:2a=0.03:2b=0.06:s=9,hqdn3d=4:3:7:6",
    "maxima": "nlmeans=s=3.5:p=7:r=13",
}
DENOISE_LABEL = {"off": "Apagado", "suave": "Suave", "media": "Media", "fuerte": "Fuerte", "maxima": "Máxima (lenta)"}

PRESETS = {
    "4k_h264": {"label": "4K H.264 (stock)", "w": 3840, "h": 2160, "ext": "mp4",
                "v": ["-c:v", "h264_videotoolbox", "-b:v", "130M", "-maxrate", "160M", "-profile:v", "high",
                      "-pix_fmt", "yuv420p"]},
    "4k_hevc10": {"label": "4K HEVC 10-bit", "w": 3840, "h": 2160, "ext": "mp4",
                  "v": ["-c:v", "hevc_videotoolbox", "-b:v", "100M", "-profile:v", "main10", "-tag:v", "hvc1",
                        "-pix_fmt", "p010le"]},
    "4k_prores": {"label": "4K ProRes 422 HQ", "w": 3840, "h": 2160, "ext": "mov",
                  "v": ["-c:v", "prores_videotoolbox", "-profile:v", "hq", "-pix_fmt", "p210le"]},
    "1080_h264": {"label": "1080p H.264", "w": 1920, "h": 1080, "ext": "mp4",
                  "v": ["-c:v", "h264_videotoolbox", "-b:v", "45M", "-profile:v", "high", "-pix_fmt", "yuv420p"]},
    "vertical_h264": {"label": "Vertical 9:16 1080×1920", "w": 1080, "h": 1920, "ext": "mp4", "vertical": True,
                      "v": ["-c:v", "h264_videotoolbox", "-b:v", "45M", "-profile:v", "high", "-pix_fmt", "yuv420p"]},
}


def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **kw)


def probe(path):
    out = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=codec_name,profile,pix_fmt,width,height,r_frame_rate:format=duration",
               "-of", "json", str(path)]).stdout
    j = json.loads(out)
    st = j["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    m = {
        "duration": float(j["format"]["duration"]),
        "width": st["width"], "height": st["height"],
        "fps": round(float(num) / float(den), 3), "fps_raw": st["r_frame_rate"],
        "codec": st["codec_name"], "pix_fmt": st["pix_fmt"], "profile": st.get("profile", ""),
    }
    m["white_peak"] = white_peak(path, m)
    return m


def white_peak(path, m):
    """Luminancia máxima real del clip como fracción del máximo del códec (1.0 = 1023 en 10 bits)."""
    bits = 10 if "10" in m["pix_fmt"] else (12 if "12" in m["pix_fmt"] else 8)
    mx = 2 ** bits - 1
    peaks = []
    for f in (0.1, 0.3, 0.5, 0.7, 0.9):
        err2 = subprocess.run([FFMPEG, "-v", "info", "-ss", f"{m['duration'] * f:.2f}", "-i", str(path),
                               "-frames:v", "1", "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YMAX",
                               "-f", "null", "-"], capture_output=True, text=True).stderr
        for line in err2.splitlines():
            if "YMAX=" in line:
                peaks.append(float(line.split("YMAX=")[1]) / mx)
    return round(max(peaks), 4) if peaks else 0.0


def frame_jpeg(path, t, meta, width=1920):
    vf = to_rgb(meta, width, -2)
    return run([FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", vf,
                "-q:v", "2", "-f", "image2pipe", "-c:v", "mjpeg", "-"]).stdout


def crop_png(path, t, cx, cy, meta, denoise="off", cw=960, ch=540):
    """Recorte al 100% (resolución nativa), con o sin reducción de ruido."""
    W, H = meta["width"], meta["height"]
    x = int(min(max(cx * W - cw / 2, 0), W - cw)) // 2 * 2
    y = int(min(max(cy * H - ch / 2, 0), H - ch)) // 2 * 2
    pre = 0.25 if t > 0.3 else 0
    chain = [f"crop={cw}:{ch}:{x}:{y}"]
    dn = DENOISE.get(denoise)
    if dn:
        chain.append(dn)
    chain.append(to_rgb(meta, cw, ch))
    chain.append(f"select='gte(t\\,{pre - 0.02:.2f})'")
    return run([FFMPEG, "-v", "error", "-ss", f"{max(t - pre, 0):.3f}", "-i", str(path), "-vf", ",".join(chain),
                "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"]).stdout


def _raw_rgb(path, t, w, h, meta=None):
    raw = run([FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
               "-vf", to_rgb(meta or {}, w, h) + ",format=rgb48le", "-f", "rawvideo", "-"]).stdout
    return np.frombuffer(raw, dtype="<u2").reshape(h, w, 3).astype(np.float64) / 65535.0


def estimate_noise(path, meta):
    """Ruido (en niveles de 8 bits) medido a resolución nativa en zonas planas y oscuras."""
    W, H = meta["width"], meta["height"]
    sig = []
    for frac in (0.3, 0.7):
        img = _raw_rgb(path, meta["duration"] * frac, W, H, meta)
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


def analyze(path, meta):
    """Corrección automática natural para stock: limpia, sin look cinematográfico."""
    w, h = 480, 270
    frames = [_raw_rgb(path, meta["duration"] * f, w, h, meta) for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    px = np.concatenate([f.reshape(-1, 3) for f in frames])
    Y = px @ np.array([0.2126, 0.7152, 0.0722])
    # Quemado: con los superblancos recuperados el blanco de la cámara queda en ~0.964, no en 1
    clip_hi = float((Y > (0.955 if knee(meta) else 0.97)).mean())
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

    sigma = estimate_noise(path, meta)
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
    raw = run([FFMPEG, "-v", "error", "-ss", f"{t0:.2f}", "-i", str(path), "-frames:v", str(n),
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


STD_FPS = [(24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1), (50, 1), (60000, 1001), (60, 1)]


def proxy_video(src, meta, out, width=1920):
    """Copia ligera para reproducir en el visor (el navegador no lee H.264 4:2:2 10-bit de la Sony).

    Mismo tratamiento que los fotogramas del visor (superblancos incluidos); el color se aplica
    encima en tiempo real con la LUT, así que no hace falta regenerarla al mover los controles.
    """
    k = knee(meta)
    vf = (k + "," if k else "") + (f"scale={width}:-2:flags=bicubic:in_color_matrix=bt709:in_range=tv:"
                                   "out_color_matrix=bt709:out_range=tv,format=yuv420p")
    tmp = Path(out).with_name(Path(out).stem + ".parcial.mp4")
    run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf,
         "-c:v", "h264_videotoolbox", "-b:v", "16M", "-g", "15", "-r", meta["fps_raw"],
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)])
    Path(tmp).replace(out)
    return Path(out)


def denoise_proxy(src_proxy, out, level):
    """Copia de reproducción con la reducción de ruido (sobre la copia ligera: rápido, para mirar)."""
    tmp = Path(out).with_name(Path(out).stem + ".parcial.mp4")
    run([FFMPEG, "-v", "error", "-y", "-i", str(src_proxy), "-map", "0:v:0", "-map", "0:a:0?", "-vf", DENOISE[level],
         "-c:v", "h264_videotoolbox", "-b:v", "16M", "-g", "15", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-colorspace", "bt709", "-c:a", "copy", "-movflags", "+faststart", str(tmp)])
    Path(tmp).replace(out)
    return Path(out)


def compare_video(orig, stabilized, meta, out, width=960):
    """Video de comparación: original a la izquierda, estabilizado a la derecha, sincronizados.

    Sirve para juzgar la estabilización en movimiento (en un fotograma quieto no se nota).
    """
    h = round(width * 9 / 16 / 2) * 2
    k = knee(meta)
    pre = (k + ",") if k else ""
    side = (f"{pre}scale={width}:{h}:flags=bicubic:in_color_matrix=bt709:in_range=tv:"
            f"out_color_matrix=bt709:out_range=tv,format=yuv420p,setpts=PTS-STARTPTS")
    fc = f"[0:v]{side}[a];[1:v]{side}[b];[a][b]hstack=inputs=2[v]"
    tmp = Path(out).with_name(Path(out).stem + ".parcial.mp4")
    run([FFMPEG, "-v", "error", "-y", "-i", str(orig), "-i", str(stabilized), "-filter_complex", fc,
         "-map", "[v]", "-an", "-c:v", "h264_videotoolbox", "-b:v", "12M", "-r", meta["fps_raw"],
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         "-movflags", "+faststart", "-shortest", str(tmp)])
    Path(tmp).replace(out)
    return Path(out)


def _fps(raw):
    n, d = raw.split("/")
    return float(n) / float(d)


def slow_options(fps_raw, max_slow):
    """Velocidades posibles SIN inventar fotogramas: el material se muestra a un fps estándar menor.
    Ej. 59.94p → 50p = 1.2× más lento; 59.94p → 29.97p = 2×."""
    src = _fps(fps_raw)
    ntsc = fps_raw.endswith("/1001")
    opts = [(1.0, fps_raw)]
    for n, d in STD_FPS:
        f = n / d
        if n in (24, 30, 60) and ntsc or d == 1001 and not ntsc:
            continue  # misma familia que la cámara (29.97 con 59.94; 30 con 60). 25/50 valen para ambas
        if f < src - 0.01 and src / f <= max_slow + 0.01:
            opts.append((round(src / f, 4), f"{n}/{d}"))
    return sorted(opts)


def plan(duration, fps_raw, trim_in, trim_out, seg):
    """Regla de cortes: sacar el MÁXIMO de clips de al menos `min` segundos.

    Si ralentizar (hasta `max_slow`) permite sacar un clip más, se ralentiza lo mínimo necesario.
    Lo que sobra se reparte en partes iguales. Devuelve los tramos en tiempo del original.
    """
    start = trim_in or 0.0
    end = min(trim_out or duration, duration)
    total = max(end - start, 0)
    out = {"segments": [(start, end)], "speed": 1.0, "fps_raw": fps_raw, "clip_len": total, "short": False}
    if not seg.get("enabled", True) or total <= 0:
        return out
    lo, hi = float(seg.get("min", 12)), float(seg.get("max", 14))
    opts = slow_options(fps_raw, float(seg.get("max_slow", 1.2)))
    count = {sp: int((total * sp + 0.05) / lo) for sp, _ in opts}  # 0.05 s de tolerancia (59.94→50 = 1.1988×)
    best = max(count.values())
    if best == 0:  # ni ralentizando llega al mínimo: un solo clip lo más largo posible
        sp, fr = opts[-1]
        out.update(speed=sp, fps_raw=fr, clip_len=total * sp, short=True)
        return out
    cands = [(sp, fr) for sp, fr in opts if count[sp] == best]
    # entre las que dan el máximo, preferir la que deja clips dentro del rango; si no, la más lenta posible = la menor
    inside = [(sp, fr) for sp, fr in cands if lo <= total * sp / best <= hi]
    sp, fr = (inside or cands)[0]
    step = total / best
    out.update(segments=[(start + i * step, start + (i + 1) * step) for i in range(best)],
               speed=sp, fps_raw=fr, clip_len=step * sp)
    return out


def segments(duration, trim_in, trim_out, seg, fps_raw="60000/1001"):
    return plan(duration, fps_raw, trim_in, trim_out, seg)["segments"]


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
        g = _raw_rgb(path, meta["duration"] * f, W, H, meta).mean(2)
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


def rotate_zoom(deg, w, h):
    """Zoom necesario para que, al girar, no aparezcan bordes (igual que el visor)."""
    a = math.radians(abs(deg))
    return math.cos(a) + max(w / h, h / w) * math.sin(a)


def rotate_filter(deg, w, h):
    """Endereza girando `deg` grados (positivo = sentido horario) y recorta para llenar el cuadro."""
    if abs(deg) < 0.005:
        return None
    z = rotate_zoom(deg, w, h)
    sw, sh = math.ceil(w * z / 2) * 2, math.ceil(h * z / 2) * 2
    return (f"scale={sw}:{sh}:flags=lanczos,"
            f"rotate={math.radians(deg):.6f}:ow={w}:oh={h}:bilinear=1")


def export_cmd(src, out, a, b, preset_key, cube_path, settings, meta, keep_audio, speed=1.0, fps_raw=None):
    P = PRESETS[preset_key]
    fps_raw = fps_raw or meta["fps_raw"]
    chain = []
    if speed != 1.0:  # ralentizar sin inventar fotogramas: mismos fotogramas, mostrados a menor fps
        chain.append(f"setpts=(PTS-STARTPTS)*{_fps(meta['fps_raw']) / _fps(fps_raw):.6f}")
    dn = DENOISE.get(settings.get("denoise", "off"))
    if dn:
        chain.append(dn)
    k = knee(meta)
    if k:
        chain.append(k)
    chain.append(f"scale=in_color_matrix=bt709:in_range=tv:out_color_matrix=bt709:out_range=pc,format=gbrp16le")
    chain.append(f"lut3d=file='{cube_path}':interp=trilinear")
    rot = rotate_filter(float(settings.get("rotate") or 0), meta["width"], meta["height"])
    if rot:
        chain.append(rot)
    if P.get("vertical"):
        chain.append("crop=ih*9/16:ih")
    chain.append(f"scale={P['w']}:{P['h']}:flags=lanczos:in_range=pc:out_color_matrix=bt709:out_range=tv")
    chain.append("setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
    cmd = [FFMPEG, "-hide_banner", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src),
           "-vf", ",".join(chain), "-map", "0:v:0"]
    if keep_audio:
        cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "320k"]
        if speed != 1.0:
            cmd += ["-af", f"atempo={_fps(fps_raw) / _fps(meta['fps_raw']):.6f}"]
    cmd += P["v"]
    cmd += ["-write_tmcd", "0"] if P["ext"] in ("mp4", "mov") else []
    cmd += ["-r", fps_raw, "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out)]
    return cmd


# ------------------------------------------------------------------ manchas del sensor (polvo)
# El polvo no tapa la imagen: la oscurece un poco, siempre en el mismo punto del sensor y con
# borde suave. Se mide cuánto oscurece (T, de 0 a 1) y se divide por T: no se inventan píxeles.
def _spot_crop_frames(path, meta, x, y, S, n=48):
    """Recortes de la zona en los fotogramas clave (rápido: no decodifica el resto)."""
    W, H = meta["width"], meta["height"]
    x0 = int(min(max(x - S // 2, 0), W - S)) // 2 * 2
    y0 = int(min(max(y - S // 2, 0), H - S)) // 2 * 2
    raw = run([FFMPEG, "-v", "error", "-skip_frame", "nokey", "-i", str(path), "-vf",
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
    run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray16le", "-s", f"{C}x{C}", "-i", "-",
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
    run([FFMPEG, "-v", "error", "-y", "-i", str(src), *inputs, "-filter_complex", fc + f";{last}format=p210le[v]",
         "-map", "[v]", "-map", "0:a:0?", "-c:v", "prores_videotoolbox", "-profile:v", "hq",
         "-c:a", "pcm_s16le", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-r", meta["fps_raw"], str(tmp)])
    tmp.replace(out)
    return Path(out)
