import subprocess

import numpy as np

from kanu import config
from kanu.core import spots
from kanu.infra import ffmpeg as ff


def _dusty_video(path, cx=400, cy=150, a=0.35, s=14):
    """Textura que se mueve (como una toma real) con una mancha de polvo fija."""
    W, H, n = 640, 360, 45
    rng = np.random.default_rng(1)
    tex = rng.random((H + 60, W + 60)) * 0.5 + 0.25
    k = np.ones(5) / 5
    tex = np.apply_along_axis(lambda v: np.convolve(v, k, "same"), 0, tex)
    tex = np.apply_along_axis(lambda v: np.convolve(v, k, "same"), 1, tex)
    yy, xx = np.mgrid[0:H, 0:W]
    T = 1 - a * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / s ** 2)
    frames = [(tex[i:i + H, i:i + W] * T * 255).astype(np.uint8) for i in range(n)]
    subprocess.run([config.FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
                    "-r", "30", "-i", "-", "-c:v", "mjpeg", "-q:v", "2", "-pix_fmt", "yuvj420p", str(path)],
                   input=b"".join(f.tobytes() for f in frames), check=True)


def test_finds_spot_center_and_strength(tmp_path):
    v = tmp_path / "polvo.mov"
    _dusty_video(v)
    m = ff.probe(v)
    sp = spots.measure_spot(v, m, 405, 145, 30)          # clic unos px fuera del centro
    assert sp is not None
    assert abs(sp["x"] - 400) <= 3 and abs(sp["y"] - 150) <= 3
    assert 0.25 < sp["a"] < 0.45


def test_no_false_spot_on_clean_area(tmp_path):
    v = tmp_path / "polvo.mov"
    _dusty_video(v)
    assert spots.measure_spot(v, ff.probe(v), 150, 250, 30) is None
