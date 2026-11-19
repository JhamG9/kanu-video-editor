import numpy as np

from kanu.core import grade, style


def test_learns_an_edit_from_a_pair():
    rng = np.random.default_rng(3)
    src = rng.random((20000, 3)) ** 1.4
    truth = {"shadows": 30, "highlights": -30, "temperature": 8, "vibrance": 15}
    dst = grade.apply(src, {**grade.DEFAULTS, **truth})
    params, loss = style.fit_pair(src, dst)
    assert loss < 0.002
    got = grade.apply(src, {**grade.DEFAULTS, **params})
    assert np.abs(np.percentile(got, [10, 50, 90]) - np.percentile(dst, [10, 50, 90])).max() < 0.02


def test_scene_features_are_stable():
    px = np.random.default_rng(0).random((5000, 3))
    f = style.scene_features(px)
    assert len(f) == 8 and all(np.isfinite(f))
