"""Los tests usan una carpeta de datos temporal: nunca tocan los videos ni ajustes reales."""
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

DATA = Path(tempfile.mkdtemp(prefix="kanu-tests-"))
os.environ["KANU_DATA"] = str(DATA)          # antes de importar kanu


@pytest.fixture(scope="session")
def data_dir():
    return DATA


@pytest.fixture(scope="session")
def tiny_video(tmp_path_factory):
    """Video de prueba de 3 s (640×360, 30p) generado con ffmpeg."""
    from kanu import config
    out = tmp_path_factory.mktemp("v") / "PRUEBA.mp4"
    subprocess.run([config.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-g", "15", str(out)], check=True)
    return out
