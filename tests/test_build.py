"""End-to-end build of the fixture presentation through LibreOffice."""

import shutil

import numpy as np
import pytest
from fixtures import LIST_BOX, RECT_BOX, make_package
from PIL import Image

from crappy.build import build

pytestmark = [
    pytest.mark.soffice,
    pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")),
                       reason="LibreOffice not installed"),
]

SIZE = (640, 360)


def _box(frac):
    """Pixel slices of a box given in page fractions, one pixel larger for anti-aliased edges."""
    x0, y0, x1, y1 = frac
    w, h = SIZE
    return (slice(max(0, int(y0 * h) - 1), min(h, int(y1 * h) + 2)),
            slice(max(0, int(x0 * w) - 1), min(w, int(x1 * w) + 2)))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("build")
    odp = tmp / "talk.odp"
    make_package().save(odp)
    manifest = build(odp, tmp / "out", size=SIZE, workers=2, log=lambda *_: None)
    return manifest, tmp / "out"


def _steps(out, number):
    """Every click step of a slide, composed (background + layers at the end of the step)."""
    from crappy.player.deck import Deck
    from crappy.preview import compose
    deck = Deck.load(out / "manifest.json")
    slide = deck.slides[number - 1]
    return [compose(slide, k, deck.size).astype(int) for k in range(slide.n_steps)]


def test_manifest(built):
    manifest, _ = built
    dark, steps = manifest["slides"]
    assert (dark["name"], len(dark["steps"]), dark["transition"]["kind"]) == ("dark", 1, "cut")
    assert steps["transition"] == {"kind": "fade", "duration": 1.0, "source": "libreoffice",
                                   "lo_type": "fade/crossfade"}
    assert [len(s["events"]) for s in steps["steps"]] == [0, 1, 1]
    assert [e["kind"] for s in steps["steps"] for e in s["events"]] == ["show", "fade_in"]
    assert steps["steps"][2]["duration"] == 0.5
    # one base layer (master + static text), the rectangle and the third bullet on their own
    assert [layer["unit"] is None for layer in steps["layers"]] == [True, False, False]
    assert all(not u["visible"] for u in steps["units"].values())
    assert not manifest["warnings"] and not dark["warnings"] and not steps["warnings"]


def test_background_classes(built):
    manifest, _ = built
    assert [s["background_class"] for s in manifest["slides"]] == ["dark", "light"]


def test_automatic_text_colour_follows_background(built):
    manifest, out = built
    dark = np.asarray(Image.open(out / manifest["slides"][0]["layers"][0]["file"]))
    text = dark[..., 3] > 250
    assert text.sum() > 50 and dark[text][:, :3].min() > 240         # white text on the black slide


def test_rebuilt_slides_match_libreoffice(built):
    manifest, _ = built
    for s in manifest["slides"]:
        assert s["check_mismatch"] is not None and s["check_mismatch"] < 1e-3


def test_backgrounds(built):
    manifest, out = built
    dark_bg = np.asarray(Image.open(out / manifest["slides"][0]["background"]))
    light_bg = np.asarray(Image.open(out / manifest["slides"][1]["background"]))
    assert dark_bg.max() < 10 and light_bg.min() > 245


def test_click_steps(built):
    _, out = built
    s0, s1, s2 = _steps(out, 2)                           # white slide
    rect, lst = _box(RECT_BOX), _box(LIST_BOX)
    differs = lambda a, b: np.abs(a - b).max(-1) > 2      # noqa: E731

    # click 1: only the rectangle appears, red inside its anti-aliased edges
    assert s0[rect].min() > 245
    inside = s1[rect][2:-2, 2:-2]
    assert (inside[..., 0] > 245).all() and (inside[..., 1:] < 10).all()
    changed = differs(s0, s1)
    changed[rect] = False
    assert not changed.any()
    # click 2: something appears in the list box (bullet 3) and nowhere else
    changed = differs(s1, s2)
    assert changed[lst].sum() > 100
    changed[lst] = False
    assert not changed.any()
    # bullets 1-2 are visible from the start and do not move
    rows = np.flatnonzero(differs(s1[lst], 255).any(axis=1))
    first_new = np.flatnonzero(differs(s2[lst], s1[lst]).any(axis=1))[0]
    assert rows[0] < first_new
    assert not differs(s0[lst][:first_new], s2[lst][:first_new]).any()


def test_cache(built, tmp_path):
    manifest, out = built
    again = build(manifest["source"], out, size=SIZE, log=lambda *_: None)
    assert again["source_key"] == manifest["source_key"]
    assert again["build_seconds"] == manifest["build_seconds"]   # loaded, not rebuilt
