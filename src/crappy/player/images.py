"""Composited slide pictures (background + step overlay), prepared in worker threads."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtGui import QImage, QPainter

from crappy.player.deck import Deck
from crappy.player.timeline import Pos


def compose(background_path, overlay_path) -> QImage:
    """QPainter on a QImage is allowed outside the GUI thread."""
    image = QImage(str(background_path)).convertToFormat(QImage.Format.Format_RGB32)
    overlay = QImage(str(overlay_path))
    if image.isNull() or overlay.isNull():
        raise OSError(f"cannot read {background_path} or {overlay_path}")
    painter = QPainter(image)
    painter.drawImage(0, 0, overlay)
    painter.end()
    return image


def load(path) -> QImage:
    image = QImage(str(path))
    if image.isNull():
        raise OSError(f"cannot read {path}")
    return image


class SlideImages:
    """Pictures by key: ("composite", pos), ("background", slide index) or ("overlay", pos)."""

    def __init__(self, deck: Deck, workers: int = 3):
        self.deck = deck
        self._pool = ThreadPoolExecutor(workers, thread_name_prefix="crappy-images")
        self._jobs: dict[tuple, Future[QImage]] = {}

    def request(self, key: tuple) -> Future[QImage]:
        job = self._jobs.get(key)
        if job is None:
            kind, where = key
            if kind == "composite":
                slide = self.deck.slides[where.slide]
                job = self._pool.submit(compose, slide.background, slide.overlays[where.step])
            elif kind == "background":
                job = self._pool.submit(
                    lambda p: load(p).convertToFormat(QImage.Format.Format_RGB32), self.deck.slides[where].background)
            else:
                job = self._pool.submit(load, self.deck.slides[where.slide].overlays[where.step])
            self._jobs[key] = job
        return job

    def get(self, pos: Pos) -> QImage:
        return self.request(("composite", pos)).result()

    def background(self, slide: int) -> QImage:
        return self.request(("background", slide)).result()

    def overlay(self, pos: Pos) -> QImage:
        return self.request(("overlay", pos)).result()

    def keep(self, keys: list[tuple]) -> None:
        """Preload these pictures and forget the others."""
        wanted = set(keys)
        for key in list(self._jobs):
            if key not in wanted:
                self._jobs.pop(key).cancel()
        for key in keys:
            self.request(key)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
