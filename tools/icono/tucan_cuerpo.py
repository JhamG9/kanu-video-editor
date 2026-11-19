"""El tucán de Kanu de cuerpo completo, parado sobre una rama.

Reutiliza el dibujo del icono (tucan.py): misma cabeza, pico, ojo, pechera y plumaje,
en un lienzo más alto, y le agrega vientre, cola larga y patas que agarran la rama.

    from tucan_cuerpo import render
    t = render()   # dict: ink, paper, feet (máscaras al doble), K, branch_y; coordenadas del icono (1024 + SHIFT)
"""
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
HT = 1420                     # alto del lienzo (en el espacio de 1024 del icono)
BRANCH_Y = 1000               # parte de arriba de la rama, donde se apoyan los dedos


def render():
    src = (HERE / "tucan.py").read_text().split("# ------------------------------------------------------------------ composición")[0]
    src = (src.replace("Y, X = np.mgrid[0:N, 0:W]", "NH = int(HT * K)\nY, X = np.mgrid[0:NH, 0:W]")
              .replace("(N, W)", "(NH, W)").replace("min(N,", "min(NH,")
              .replace("int(1024 / scale) + 3", "int(HT / scale) + 3"))
    a, b = src.split("M = {k: fill(v) for k, v in dict(", 1)
    ns = {"__file__": str(HERE / "tucan.py"), "HT": HT}
    exec(compile(a, "tucan.py", "exec"), ns)

    # silueta nueva: el cuerpo se cierra en un vientre redondo; el ala termina sobre la cola
    path = ns["path"]
    ns["head_body"] = path((318, 905), ((268, 800), (270, 700), (282, 610)), ((284, 470), (300, 330), (380, 268)),
                           ((440, 222), (530, 214), (582, 246)), ((596, 300), (600, 380), (596, 452)),
                           ((640, 520), (700, 610), (712, 720)), ((728, 830), (706, 915), (640, 950)),
                           ((560, 990), (420, 980), (318, 905)))
    ns["wing"] = path((300, 560), ((340, 650), (408, 780), (432, 925)), ((392, 960),), ((318, 905),),
                      ((268, 800), (276, 670), (300, 560)))
    exec(compile("M = {k: fill(v) for k, v in dict(" + b, "tucan.py", "exec"), ns)

    X, Y, K = ns["X"], ns["Y"], ns["K"]
    fill, lines, proj, blur, edge, noise, dist = (ns[k] for k in ("fill", "lines", "proj", "blur", "edge", "noise", "dist"))
    ink, paper, body = ns["ink"], ns["paper"], ns["M"]["body"]
    light = ns["light"]

    # ------------------------------------------------------------------ cola: larga, negra, cae detrás de la rama
    tail = fill(path((300, 860), ((350, 900), (400, 930), (408, 960)), ((404, 1120), (380, 1260), (352, 1392)),
                     ((330, 1402), (290, 1400), (262, 1386)), ((262, 1250), (270, 1060), (300, 860))))
    tail *= 1 - body
    tu = X + (Y - 860) * 0.14                                    # coordenada a lo ancho de la cola
    sep = np.exp(-((np.abs(((tu - 262) / 36) % 1.0 - 0.5) - 0.5) / 0.05) ** 2)   # separación entre plumas
    tone_t = 0.90 - 0.18 * light - 0.55 * sep - 0.25 * np.exp(-((tu - 300) / 14) ** 2)  # brillo a lo largo
    t_ink = tail * lines(tu, 4.6, tone_t)
    ragged = (Y > 1350 + 18 * np.sin(X / 9)) * tail                                # puntas de las plumas
    ink = np.maximum(ink * (1 - tail), t_ink * (1 - ragged))
    paper = np.clip(paper + tail * (1 - ragged), 0, 1)
    ink = np.maximum(ink, edge(tail * (1 - ragged), 2.2))

    # ------------------------------------------------------------------ patas y dedos (dos adelante, dos atrás)
    legs = np.zeros_like(X)
    toes = np.zeros_like(X)

    def stroke(pts, w):
        m = np.zeros_like(X)
        pts = np.array(pts, float)
        t = np.linspace(0, 1, 60)
        seg = np.array([np.interp(t, np.linspace(0, 1, len(pts)), pts[:, k]) for k in (0, 1)]).T
        for x0, y0 in seg:
            m = np.maximum(m, (np.hypot(X - x0, Y - y0) < w).astype(np.float32))
        return m

    for lx in (520, 588):
        legs = np.maximum(legs, stroke([(lx, 950), (lx + 4, 972), (lx + 6, BRANCH_Y - 4)], 11))
        toes = np.maximum(toes, stroke([(lx + 6, BRANCH_Y - 6), (lx + 30, BRANCH_Y - 2), (lx + 46, BRANCH_Y + 12),
                                        (lx + 48, BRANCH_Y + 24)], 6.5))
        toes = np.maximum(toes, stroke([(lx + 6, BRANCH_Y - 6), (lx + 22, BRANCH_Y + 2), (lx + 30, BRANCH_Y + 18),
                                        (lx + 28, BRANCH_Y + 30)], 6.0))
        toes = np.maximum(toes, stroke([(lx + 4, BRANCH_Y - 6), (lx - 20, BRANCH_Y), (lx - 32, BRANCH_Y + 16),
                                        (lx - 30, BRANCH_Y + 28)], 6.0))
        for cx in (lx + 48, lx + 28, lx - 30):                                     # uñas
            toes = np.maximum(toes, (np.hypot(X - cx, Y - (BRANCH_Y + 30)) < 4).astype(np.float32))
    feet = np.clip(legs * (1 - body) + toes, 0, 1)
    f_tone = 0.42 + 0.3 * np.clip((X - 540) / 80, 0, 1)
    f_ink = feet * np.maximum(lines(Y, 4.0, f_tone), lines(X + Y * 0.3, 7.0, 0.25))   # escamas de la pata
    ink = np.maximum(ink * (1 - feet), f_ink)
    ink = np.maximum(ink, edge(feet, 1.8))
    paper = np.clip(paper + feet, 0, 1)
    chest = np.clip(ns["M"]["bib"] + ns["M"]["band"], 0, 1)          # pecho (azul en el tucán de páramo)
    return {"ink": np.clip(ink, 0, 1), "paper": paper, "feet": toes, "chest": chest, "K": K, "branch_y": BRANCH_Y}


if __name__ == "__main__":                       # vista previa del tucán solo
    import subprocess
    import sys
    t = render()
    ink, paper = t["ink"], t["paper"]
    blue = np.array([128, 166, 208], np.float32) / 255
    cream = np.array([247, 241, 226], np.float32) / 255
    black = np.array([20, 18, 16], np.float32) / 255
    img = blue * (1 - paper[..., None]) + cream * paper[..., None]
    img = img * (1 - ink[..., None]) + black * ink[..., None]
    h, w = img.shape[0] // 2 * 2, img.shape[1] // 2 * 2
    img = img[:h, :w].reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3))
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("tucan_cuerpo_preview.png")
    subprocess.run(["/opt/homebrew/bin/ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{w // 2}x{h // 2}", "-i", "-", str(out)],
                   input=(np.clip(img, 0, 1) * 255).astype(np.uint8).tobytes(), check=True)
    print("listo:", out)
