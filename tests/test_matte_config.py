# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

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
    assert cfg.overrides["Conclusion"].kind == "push"


def test_movie_sections(tmp_path):
    for i in range(3):
        (tmp_path / f"frame_{i:05d}.png").write_bytes(b"")
    path = tmp_path / "t.crappy.toml"
    path.write_text('[defaults]\noverlay_out = 0.2\n[movie]\nframes = "frame_*.png"\nfps = 24\n')
    cfg = load_config(path)
    (m,) = cfg.movies
    assert (m.fps, m.overlay_out, m.overlay_in) == (24, 0.2, 0.5)
    assert m.index_of_stem() == {"frame_00000": 0, "frame_00001": 1, "frame_00002": 2}
    assert len(cfg.media_files()) == 3

    path.write_text('[[movie]]\nframes = "frame_0000[01].png"\n[[movie]]\nframes = "frame_00002.png"\n')
    assert [len(m.frames) for m in load_config(path).movies] == [2, 1]


@pytest.mark.parametrize("body, message", [
    ('[movie]\nfps = 30', "'frames' is required"),
    ('[transition.a]\nkind = "fade"\noverlay_in = 1', "only apply to clips"),
    ('[transition.a]\nfps = 25', "needs 'frames'"),
    ('[movie]\nframes = "nothing*.png"', "no file matches"),
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
