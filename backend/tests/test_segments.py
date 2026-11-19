import pytest

from kanu.core import segments

SEG = {"enabled": True, "min": 12, "max": 14, "max_slow": 1.2}


@pytest.mark.parametrize("dur,clips,length,speed", [
    (10, 1, 12.0, 1.2),      # se ralentiza para llegar a 12 s
    (16, 1, 16.0, 1.0),      # un solo clip: entero, a velocidad normal
    (22, 2, 13.2, 1.2),
    (32, 3, 12.8, 1.2),
    (40, 4, 12.0, 1.2),
])
def test_stock_cuts_table(dur, clips, length, speed):
    p = segments.plan(dur, "60000/1001", 0, None, SEG)
    assert len(p["segments"]) == clips
    assert p["clip_len"] == pytest.approx(length, abs=0.05)
    assert p["speed"] == pytest.approx(speed, abs=0.01)


def test_slowdown_never_invents_frames():
    opts = dict(segments.slow_options("60000/1001", 2))
    assert opts[1.0] == "60000/1001"
    assert set(opts.values()) <= {"60000/1001", "50/1", "30000/1001", "25/1"}


def test_trim_limits_the_plan():
    p = segments.plan(30, "60000/1001", 5, 19, SEG)
    assert p["segments"][0][0] == 5 and p["segments"][-1][1] == 19
