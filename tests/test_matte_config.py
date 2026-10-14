import numpy as np
import pytest

from crappy.config import ConfigError, load_config, natural_key
from crappy.matte import over, unmatte


@pytest.mark.parametrize("b1, b2", [((0, 0, 0), (0, 0, 255)),            # dark pair
                                    ((255, 255, 255), (255, 255, 0)),    # light pair
                                    ((0, 0, 0), (255, 255, 255))])
def test_unmatte_recovers_layer(b1, b2):
    rng = np.random.default_rng(0)
    rgb = rng.random((64, 64, 3))
    alpha = rng.random((64, 64, 1))
    alpha[:8] = 0
    alpha[8:16] = 1

    def render(backdrop):
        return ((rgb * alpha + (1 - alpha) * np.array(backdrop) / 255) * 255).round().astype(np.uint8)

    r1, r2 = render(b1), render(b2)
    layer = unmatte(r1, r2, b1, b2)
    assert np.abs(layer[..., 3] / 255 - alpha[..., 0]).max() < 2 / 255
    assert (layer[:8] == 0).all()
    # colour is only well defined where the layer is not nearly transparent
    solid = alpha[..., 0] > 0.2
    assert np.abs(layer[..., :3] / 255 - rgb)[solid].max() < 0.03
    # compositing over the original backdrops gives the renders back
    for r, b in ((r1, b1), (r2, b2)):
        assert np.abs(over(layer, np.broadcast_to(np.array(b, np.uint8), r.shape)).astype(int) - r).max() <= 2


def test_natural_sort():
    names = ["f10.png", "f2.png", "f1.png"]
    assert sorted(names, key=natural_key) == ["f1.png", "f2.png", "f10.png"]


def test_config(tmp_path):
    frames = tmp_path / "renders"
    frames.mkdir()
    for i in (1, 2, 10):
        (frames / f"f{i}.png").write_bytes(b"")
    path = tmp_path / "talk.crappy.toml"
    path.write_text("""
[defaults]
overlay_in = 0.8

[transition.halo]
frames = "renders/*.png"
fps = 25

[transition."Conclusion"]
kind = "push"
side = "left"
""")
    cfg = load_config(path)
    clip = cfg.clips["halo"]
    assert [p.name for p in clip.frames] == ["f1.png", "f2.png", "f10.png"]
    assert (clip.fps, clip.overlay_in, clip.overlay_out) == (25, 0.8, 0.3)
    assert clip.duration == pytest.approx(3 / 25)
    assert cfg.overrides["Conclusion"].kind == "push"


@pytest.mark.parametrize("body, message", [
    ('[transition.a]\nframes = "none/*.png"', "no file matches"),
    ('[transition.a]\nkind = "spin"', "kind must be"),
    ('[transition.a]\nframes = "x"\nkind = "fade"', "cannot be combined"),
    ('[transition.a]\nfsp = 3', "unknown key"),
    ('[transitions.a]\nkind = "fade"', "unknown section"),
])
def test_config_errors(tmp_path, body, message):
    path = tmp_path / "t.crappy.toml"
    path.write_text(body)
    with pytest.raises(ConfigError, match=message):
        load_config(path)
