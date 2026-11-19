"""ffmpeg: lectura, fotogramas, copias de reproducción y comandos de exportación."""
import json
import math
import subprocess
from pathlib import Path

import numpy as np

from kanu import config
from kanu.core import segments as seg


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
    out = run([config.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
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
        err2 = subprocess.run([config.FFMPEG, "-v", "info", "-ss", f"{m['duration'] * f:.2f}", "-i", str(path),
                               "-frames:v", "1", "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YMAX",
                               "-f", "null", "-"], capture_output=True, text=True).stderr
        for line in err2.splitlines():
            if "YMAX=" in line:
                peaks.append(float(line.split("YMAX=")[1]) / mx)
    return round(max(peaks), 4) if peaks else 0.0


def frame_jpeg(path, t, meta, width=1920):
    vf = to_rgb(meta, width, -2)
    return run([config.FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", vf,
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
    return run([config.FFMPEG, "-v", "error", "-ss", f"{max(t - pre, 0):.3f}", "-i", str(path), "-vf", ",".join(chain),
                "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"]).stdout


def _raw_rgb(path, t, w, h, meta=None):
    raw = run([config.FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
               "-vf", to_rgb(meta or {}, w, h) + ",format=rgb48le", "-f", "rawvideo", "-"]).stdout
    return np.frombuffer(raw, dtype="<u2").reshape(h, w, 3).astype(np.float64) / 65535.0


def proxy_video(src, meta, out, width=1920):
    """Copia ligera para reproducir en el visor (el navegador no lee H.264 4:2:2 10-bit de la Sony).

    Mismo tratamiento que los fotogramas del visor (superblancos incluidos); el color se aplica
    encima en tiempo real con la LUT, así que no hace falta regenerarla al mover los controles.
    """
    k = knee(meta)
    vf = (k + "," if k else "") + (f"scale={width}:-2:flags=bicubic:in_color_matrix=bt709:in_range=tv:"
                                   "out_color_matrix=bt709:out_range=tv,format=yuv420p")
    tmp = Path(out).with_name(Path(out).stem + ".parcial.mp4")
    run([config.FFMPEG, "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf,
         "-c:v", "h264_videotoolbox", "-b:v", "16M", "-g", "15", "-r", meta["fps_raw"],
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)])
    Path(tmp).replace(out)
    return Path(out)


def denoise_proxy(src_proxy, out, level):
    """Copia de reproducción con la reducción de ruido (sobre la copia ligera: rápido, para mirar)."""
    tmp = Path(out).with_name(Path(out).stem + ".parcial.mp4")
    run([config.FFMPEG, "-v", "error", "-y", "-i", str(src_proxy), "-map", "0:v:0", "-map", "0:a:0?", "-vf", DENOISE[level],
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
    run([config.FFMPEG, "-v", "error", "-y", "-i", str(orig), "-i", str(stabilized), "-filter_complex", fc,
         "-map", "[v]", "-an", "-c:v", "h264_videotoolbox", "-b:v", "12M", "-r", meta["fps_raw"],
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         "-movflags", "+faststart", "-shortest", str(tmp)])
    Path(tmp).replace(out)
    return Path(out)


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
        chain.append(f"setpts=(PTS-STARTPTS)*{seg._fps(meta['fps_raw']) / seg._fps(fps_raw):.6f}")
    dn = DENOISE.get(settings.get("denoise", "off"))
    if dn:
        chain.append(dn)
    k = knee(meta)
    if k:
        chain.append(k)
    chain.append("scale=in_color_matrix=bt709:in_range=tv:out_color_matrix=bt709:out_range=pc,format=gbrp16le")
    chain.append(f"lut3d=file='{cube_path}':interp=trilinear")
    rot = rotate_filter(float(settings.get("rotate") or 0), meta["width"], meta["height"])
    if rot:
        chain.append(rot)
    if P.get("vertical"):
        chain.append("crop=ih*9/16:ih")
    chain.append(f"scale={P['w']}:{P['h']}:flags=lanczos:in_range=pc:out_color_matrix=bt709:out_range=tv")
    chain.append("setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
    cmd = [config.FFMPEG, "-hide_banner", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src),
           "-vf", ",".join(chain), "-map", "0:v:0"]
    if keep_audio:
        cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "320k"]
        if speed != 1.0:
            cmd += ["-af", f"atempo={seg._fps(fps_raw) / seg._fps(meta['fps_raw']):.6f}"]
    cmd += P["v"]
    cmd += ["-write_tmcd", "0"] if P["ext"] in ("mp4", "mov") else []
    cmd += ["-r", fps_raw, "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out)]
    return cmd
