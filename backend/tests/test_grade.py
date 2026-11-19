import numpy as np

from kanu.core import grade


def test_neutral_settings_do_not_change_colors():
    rgb = np.random.default_rng(0).random((5000, 3))
    out = grade.apply(rgb, dict(grade.DEFAULTS))
    assert np.abs(out - rgb).max() < 1e-9


def test_lut_size_and_order():
    lut = grade.build_lut(dict(grade.DEFAULTS), size=17)
    assert lut.shape == (17 ** 3, 3)
    assert np.allclose(lut[1], [1 / 16, 0, 0])          # el rojo varía más rápido (orden .cube)


def test_exposure_brightens_and_shadows_open():
    g = np.full((1, 3), 0.25)
    assert grade.apply(g, {"exposure": 0.5})[0, 0] > 0.25
    assert grade.apply(g, {"shadows": 50})[0, 0] > 0.25
    assert grade.apply(g, {"blacks": -50})[0, 0] < 0.25


def test_style_lut_is_applied_after_kanu():
    n = 5
    g = np.linspace(0, 1, n)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    warm = np.stack([np.minimum(1, r * 1.1), gg, b * 0.9], -1)
    try:
        grade.STYLE_LUT = warm
        mid = grade.build_lut(dict(grade.DEFAULTS), size=3)[13]   # gris medio
        assert mid[0] > 0.5 > mid[2]
    finally:
        grade.STYLE_LUT = None
