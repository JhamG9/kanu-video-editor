"""Cortes para stock: cuántos clips salen y a qué velocidad, sin inventar fotogramas."""





STD_FPS = [(24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1), (50, 1), (60000, 1001), (60, 1)]


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
