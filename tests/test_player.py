"""Player drawing and input, offscreen."""

import json

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from crappy.player import scene
from crappy.player.deck import Deck, Effect
from crappy.player.timeline import Blend, Pos, Still
from crappy.player.window import Controller, RasterView, fit

W, H = 64, 36
RED, BLUE = QColor("#ff0000"), QColor("#0000ff")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def solid(color: QColor) -> QImage:
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(color)
    return img


def to_array(img: QImage) -> np.ndarray:
    """Copy a QImage into an (H, W, 3) array (a view would die with the QImage)."""
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    rows = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    return rows[:, :img.width() * 3].reshape(img.height(), img.width(), 3).copy()


class Pictures:
    """Image provider for scene.draw from a dict of composited pictures."""

    def __init__(self, composites):
        self.composite = composites.__getitem__


def render(s, images) -> np.ndarray:
    out = QImage(W, H, QImage.Format.Format_RGB32)
    out.fill(QColor("black"))
    p = QPainter(out)
    scene.draw(p, QRectF(0, 0, W, H), s, Pictures(images))
    p.end()
    return to_array(out)


A, B = Pos(0, 0), Pos(1, 0)
IMAGES = {A: solid(RED), B: solid(BLUE)}


def test_still(app):
    assert (render(Still(A), IMAGES)[..., 0] == 255).all()


def test_fade_half(app):
    px = render(Blend(A, B, Effect("fade", 1), 0.5), IMAGES)
    assert abs(int(px[5, 5, 0]) - 128) <= 2 and abs(int(px[5, 5, 2]) - 128) <= 2


def test_fade_through_black(app):
    px = render(Blend(A, B, Effect("fade_color", 1, color="#000000"), 0.5), IMAGES)
    assert px.max() <= 2
    px = render(Blend(A, B, Effect("fade_color", 1, color="#000000"), 0.75), IMAGES)
    assert px[..., 0].max() <= 2 and abs(int(px[5, 5, 2]) - 128) <= 3


def test_push_from_left(app):
    px = render(Blend(A, B, Effect("push", 1, side="left"), 0.5), IMAGES)
    assert (px[:, : W // 2 - 1, 2] == 255).all()       # B arrived on the left half
    assert (px[:, W // 2 + 1:, 0] == 255).all()        # A pushed into the right half


def test_cover_and_uncover(app):
    px = render(Blend(A, B, Effect("cover", 1, side="right"), 0.5), IMAGES)
    assert (px[:, : W // 2 - 1, 0] == 255).all() and (px[:, W // 2 + 1:, 2] == 255).all()
    px = render(Blend(A, B, Effect("uncover", 1, side="top"), 0.5), IMAGES)
    assert (px[: H // 2 - 1, :, 0] == 255).all() and (px[H // 2 + 1:, :, 2] == 255).all()


def test_wipe(app):
    px = render(Blend(A, B, Effect("wipe", 1, side="left"), 0.25), IMAGES)
    assert (px[:, : W // 4 - 1, 2] == 255).all() and (px[:, W // 4 + 1:, 0] == 255).all()
    px = render(Blend(A, B, Effect("wipe", 1, side="bottom"), 0.25), IMAGES)
    assert (px[-H // 4 + 1:, :, 2] == 255).all() and (px[: -H // 4 - 1, :, 0] == 255).all()


def test_fit_letterboxes():
    r = fit(1920, 1080, QRectF(0, 0, 1000, 1000))
    assert (round(r.width(), 3), round(r.height(), 3), round(r.y(), 3)) == (1000, 562.5, 218.75)


# --- controller on a real (tiny) built talk ---------------------------------------


@pytest.fixture
def deck(tmp_path):
    def save(name, rgba):
        Image.fromarray(np.asarray(rgba, np.uint8)).save(tmp_path / name)
        return name

    bg = save("bg.png", np.zeros((H, W, 3)))
    clear = np.zeros((H, W, 4))
    dot = clear.copy()
    dot[10:20, 10:20] = (255, 255, 255, 255)
    slides = [
        {"number": 1, "name": "one", "hidden": False, "notes": "", "background": bg,
         "steps": [{"overlay": save("o1.png", clear), "effect": {"kind": "cut", "duration": 0}},
                   {"overlay": save("o2.png", dot), "effect": {"kind": "cut", "duration": 0}}],
         "transition": {"kind": "cut"}},
        {"number": 2, "name": "two", "hidden": False, "notes": "", "background": save("bg2.png", np.full((H, W, 3), 255)),
         "steps": [{"overlay": "o1.png", "effect": {"kind": "cut", "duration": 0}}],
         "transition": {"kind": "fade", "duration": 1.0}},
    ]
    (tmp_path / "manifest.json").write_text(json.dumps({"size": [W, H], "slides": slides}))
    return Deck.load(tmp_path / "manifest.json")


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def grab(view) -> np.ndarray:
    return to_array(view.grab().toImage())


def test_controller_keys_and_painting(app, deck):
    clock = Clock()
    c = Controller(deck, clock=clock)
    view = RasterView(c)
    view.resize(W, H)
    assert grab(view)[15, 15].max() == 0                 # step 0: dot not there yet
    c.key(Qt.Key.Key_Space)
    assert grab(view)[15, 15].min() == 255               # click: dot appears
    c.key(Qt.Key.Key_Right)                              # fade to slide 2
    clock.t = 0.5
    assert 100 < grab(view)[2, 2, 0] < 160               # half way between black and white
    assert c.timeline.animating(clock.t)
    c.key(Qt.Key.Key_Right)                              # skip to the end
    assert grab(view)[2, 2].min() == 255

    c.key(Qt.Key.Key_B)                                  # blackout
    assert grab(view).max() == 0
    c.key(Qt.Key.Key_Right)                              # first key only uncovers
    assert c.timeline.scene(clock.t) == Still(Pos(1, 0)) and grab(view)[2, 2].min() == 255

    c.key(Qt.Key.Key_1, "1")                             # type "1" + Enter: go to slide 1
    c.key(Qt.Key.Key_Return)
    assert c.timeline.scene(clock.t) == Still(Pos(0, 0)) and c.typed == ""
    c.key(Qt.Key.Key_9, "9")                             # unknown slide: ignored
    c.key(Qt.Key.Key_Enter)
    assert c.timeline.scene(clock.t) == Still(Pos(0, 0))
    view.close()


def test_clip_transitions_fall_back_to_fade(tmp_path, deck):
    data = json.loads((deck.root / "manifest.json").read_text())
    data["slides"][1]["transition"] = {"kind": "clip", "frames": ["f"] * 90, "fps": 30}
    (deck.root / "manifest.json").write_text(json.dumps(data))
    assert Deck.load(deck.root / "manifest.json").slides[1].transition == Effect("fade", 1.0)


class FakeScreen:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


def test_default_screen_prefers_an_external_output():
    from crappy.player.app import default_screen
    laptop, desk, projector = FakeScreen("eDP-1"), FakeScreen("HDMI-1"), FakeScreen("DP-2")
    assert default_screen([laptop], laptop) is laptop
    assert default_screen([desk, laptop], desk) is desk              # external, even if primary
    assert default_screen([laptop, projector], laptop) is projector
    assert default_screen([desk, laptop, projector], desk) is projector
    assert default_screen([FakeScreen("A"), FakeScreen("B")], None).name() == "A"
