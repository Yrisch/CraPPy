"""Movie clips: deducing them, encoding, decoding, building and playing."""

import shutil

import numpy as np
import pytest
from fixtures import MOVIE_SIZE, make_frames, make_movie_package
from PIL import Image

from crappy.build import analyse
from crappy.config import Config, MovieSpec, TransitionOverride
from crappy.player.deck import ClipRef
from crappy.player.window import upcoming_frames

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
needs_soffice = [pytest.mark.soffice, pytest.mark.skipif(
    not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice not installed")]


def test_clip_frames_and_overlay_fades():
    back = ClipRef("m", 30, 0, fps=30, overlay_in=0.5, overlay_out=0.3)    # 1 s, played backwards
    assert back.n_frames == 31 and back.index(0.5) == 15 and back.frame(15) == 15 and back.frame(1) == 29
    assert back.overlay_alphas(0) == (1.0, 0.0)
    out, inc = back.overlay_alphas(0.15)
    assert out == pytest.approx(0.5) and inc == 0
    out, inc = back.overlay_alphas(0.75)
    assert out == 0 and inc == pytest.approx(0.5)
    assert back.overlay_alphas(1) == (0.0, 1.0)


def test_fades_outside_the_movie():
    # text fades out 0.5 s before a 1 s movie, new text fades in 0.5 s after it
    clip = ClipRef("m", 0, 30, fps=30, overlay_in=-0.5, overlay_out=-0.5)
    assert clip.duration == pytest.approx(2.0)
    at = lambda seconds: seconds / clip.duration                          # noqa: E731
    assert clip.index(at(0.25)) == 0 and clip.overlay_alphas(at(0.25)) == pytest.approx((0.5, 0.0))
    assert clip.index(at(1.0)) == 15 and clip.overlay_alphas(at(1.0)) == (0.0, 0.0)
    assert clip.index(at(1.5)) == 30 and clip.overlay_alphas(at(1.5)) == (0.0, 0.0)
    assert clip.index(at(1.75)) == 30 and clip.overlay_alphas(at(1.75)) == pytest.approx((0.0, 0.5))
    # mixed: usual fade-out during the movie, fade-in after it
    clip = ClipRef("m", 0, 30, fps=30, overlay_in=-0.4, overlay_out=0.3)
    assert clip.duration == pytest.approx(1.4)
    assert clip.overlay_alphas(0.3 / 1.4)[0] == pytest.approx(0.0)
    assert clip.overlay_alphas(1.2 / 1.4) == pytest.approx((0.0, 0.5))


def test_upcoming_frames_skip_the_slides_own_backgrounds():
    clip = ClipRef("m", 10, 20, 30, 0.5, 0.3)
    assert upcoming_frames(clip, 0.0, +1, 4) == [11, 12, 13]           # frame 10 is slide A's background
    assert upcoming_frames(clip, 1.0, -1, 4) == [19, 18, 17]           # frame 20 is slide B's background
    assert upcoming_frames(clip, 0.5, -1, 3) == [15, 14, 13]


def test_clips_deduced_from_background_names(tmp_path):
    frames = make_frames(tmp_path / "frames")
    pkg = make_movie_package(frames)
    cfg = Config(movies=[MovieSpec(frames, fps=4)])
    slides = analyse(pkg, cfg).slides
    assert [s.background_image.name for s in slides] == ["frame_00000", "frame_00004", "frame_00001"]
    assert [s.movie_frame for s in slides] == [("movie0", 0), ("movie0", 4), ("movie0", 1)]
    assert slides[0].clip is None
    assert (slides[1].clip.start, slides[1].clip.end, slides[1].clip.duration) == (0, 4, 1.0)
    assert (slides[2].clip.start, slides[2].clip.end) == (4, 1)                    # backwards

    # an explicit transition in the side file wins over the movie
    cfg.overrides["s3"] = TransitionOverride(kind="fade")
    assert analyse(make_movie_package(frames), cfg).slides[2].clip is None
    # fade times alone tune the deduced clip instead of replacing it
    cfg.overrides["s3"] = TransitionOverride(overlay_out=0.8, overlay_in=0.1)
    clip = analyse(make_movie_package(frames), cfg).slides[2].clip
    assert (clip.start, clip.end, clip.overlay_out, clip.overlay_in) == (4, 1, 0.8, 0.1)
    analysis = analyse(make_movie_package(frames), Config(overrides={"s1": TransitionOverride(overlay_in=1)}))
    assert "not entered through a clip" in analysis.warnings[0]
    # no [movie] section: plain slides
    assert all(s.clip is None for s in analyse(make_movie_package(frames), Config()).slides)


@needs_ffmpeg
def test_encode_and_decode_any_order(tmp_path):
    from crappy import movie
    from crappy.player.movie import MovieDecoder
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    frames = make_frames(tmp_path / "frames")
    out = tmp_path / "m.mp4"
    movie.encode_frames(frames[1:], out, 4, MOVIE_SIZE)
    assert movie.frame_count(out) == 4

    dec = MovieDecoder(out, first=1)
    assert 0 not in dec and 1 in dec and 4 in dec and 5 not in dec
    for k in (4, 2, 3, 1):                                  # any order
        img = dec.request(k).result(timeout=10).convertToFormat(dec.request(k).result().Format.Format_RGB888)
        got = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3]
        want = np.asarray(Image.open(frames[k])).reshape(img.height(), -1)
        assert np.abs(got.astype(int) - want).mean() < 1.5, k
    dec.keep([2])
    assert dec.ready(2) is not None and dec.ready(4) is None
    dec.close()


@pytest.fixture(scope="module")
def movie_talk(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("movie")
    frames = make_frames(tmp / "frames")
    odp = tmp / "talk.odp"
    make_movie_package(frames).save(odp)
    (tmp / "talk.crappy.toml").write_text('[movie]\nframes = "frames/frame_*.png"\nfps = 4\n')
    return tmp, frames


@needs_ffmpeg
@pytest.mark.soffice
@pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice not installed")
def test_build_and_play_movie_talk(movie_talk):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from crappy.build import build
    from crappy.player.deck import Deck
    from crappy.player.timeline import Blend
    from crappy.player.window import Controller, RasterView
    QApplication.instance() or QApplication([])

    tmp, frames = movie_talk
    manifest = build(tmp / "talk.odp", tmp / "out", size=MOVIE_SIZE, workers=2, log=lambda *_: None)
    assert list(manifest["movies"]) == ["movie0"]
    m = manifest["movies"]["movie0"]
    assert (m["first"], m["count"]) == (0, 5)                # frames 0..4 are used
    t2, t3 = manifest["slides"][1]["transition"], manifest["slides"][2]["transition"]
    assert (t2["kind"], t2["start"], t2["end"], t2["duration"]) == ("clip", 0, 4, 1.0)
    assert (t3["start"], t3["end"]) == (4, 1)
    for s in manifest["slides"]:
        assert s["check_mismatch"] < 1e-3 and not s["warnings"], s
    # picture backgrounds are the original frames, pixel for pixel
    bg = np.asarray(Image.open(tmp / "out" / manifest["slides"][1]["background"]))
    assert (bg == np.asarray(Image.open(frames[4]))).all()

    # play: half-way through the first clip the background is frame 2
    clock = type("Clock", (), {"t": 0.0, "__call__": lambda self: self.t})()
    c = Controller(Deck.load(tmp / "out" / "manifest.json"), clock=clock)
    view = RasterView(c)
    view.resize(*MOVIE_SIZE)
    c.key(Qt.Key.Key_Right)
    clock.t = 0.5
    c._preload()
    for f in c.decoders["movie0"]._jobs.values():
        f.result(timeout=10)
    scene = c.timeline.scene(clock.t)
    assert isinstance(scene, Blend) and scene.effect.kind == "clip"
    img = view.grab().toImage().convertToFormat(view.grab().toImage().Format.Format_RGB888)
    shown = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3] \
        .reshape(img.height(), img.width(), 3).copy()
    frame2 = np.asarray(Image.open(frames[2]))
    # the bottom of the slide has no content: pure movie frame
    assert np.abs(shown[300:].astype(int) - frame2[300:]).mean() < 2
    assert c.clip_frames_late == 0
    view.close()
