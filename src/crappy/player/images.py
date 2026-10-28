"""Slide pictures, prepared in worker threads (QPainter on a QImage is allowed there).

  ("composite", pos)    background + every layer as it is at the end of click step pos.step
  ("overlay", pos)      the same layers on a transparent picture (shown over movie clips)
  ("background", slide) the background alone
Layer pictures are loaded once per slide and shared.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter

from crappy.player.animate import layer_states
from crappy.player.deck import Deck
from crappy.player.timeline import Pos


def load(path) -> QImage:
    image = QImage(str(path))
    if image.isNull():
        raise OSError(f"cannot read {path}")
    return image


def paint_layers(painter: QPainter, layers: list[QImage], slide, states, scale: float = 1.0,
                 origin: QPointF = QPointF(0, 0)) -> None:
    """Draw a slide's layers with their (opacity, dx, dy); canvas pixels scaled by `scale` from
    `origin` (the painter scales the pictures: on OpenGL, for free)."""
    for image, layer, (opacity, dx, dy) in zip(layers, slide.layers, states):
        if opacity <= 0:
            continue
        painter.setOpacity(opacity)
        if scale == 1.0 and dx == int(dx) and dy == int(dy):
            painter.drawImage(origin + QPointF(layer.x + dx, layer.y + dy), image)
        else:
            painter.drawImage(QRectF(origin.x() + (layer.x + dx) * scale, origin.y() + (layer.y + dy) * scale,
                                     image.width() * scale, image.height() * scale), image)
    painter.setOpacity(1.0)


class SlideImages:
    def __init__(self, deck: Deck, workers: int = 3):
        self.deck = deck
        self._pool = ThreadPoolExecutor(workers, thread_name_prefix="crappy-images")
        self._jobs: dict[tuple, Future[QImage]] = {}
        self._layers: dict[int, list[QImage]] = {}
        self._lock = threading.Lock()

    def layers(self, slide: int) -> list[QImage]:
        with self._lock:
            images = self._layers.get(slide)
        if images is None:
            images = [load(layer.path).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                      for layer in self.deck.slides[slide].layers]
            with self._lock:
                self._layers[slide] = images
        return images

    def _compose(self, pos: Pos, with_background: bool) -> QImage:
        slide = self.deck.slides[pos.slide]
        w, h = self.deck.size
        if with_background:
            image = load(slide.background).convertToFormat(QImage.Format.Format_RGB32)
        else:
            image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
        painter = QPainter(image)
        paint_layers(painter, self.layers(pos.slide), slide, layer_states(slide, pos.step))
        painter.end()
        return image

    def request(self, key: tuple) -> Future[QImage]:
        job = self._jobs.get(key)
        if job is None:
            kind, where = key
            if kind == "composite":
                job = self._pool.submit(self._compose, where, True)
            elif kind == "overlay":
                job = self._pool.submit(self._compose, where, False)
            else:
                job = self._pool.submit(
                    lambda p: load(p).convertToFormat(QImage.Format.Format_RGB32), self.deck.slides[where].background)
            self._jobs[key] = job
        return job

    def get(self, pos: Pos) -> QImage:
        return self.request(("composite", pos)).result()

    def background(self, slide: int) -> QImage:
        return self.request(("background", slide)).result()

    def overlay(self, pos: Pos) -> QImage:
        return self.request(("overlay", pos)).result()

    def keep(self, keys: list[tuple]) -> None:
        """Preload these pictures and forget the others (layer pictures of far slides too)."""
        wanted = set(keys)
        for key in list(self._jobs):
            if key not in wanted:
                self._jobs.pop(key).cancel()
        slides = {k[1] if k[0] == "background" else k[1].slide for k in keys}
        with self._lock:
            for s in list(self._layers):
                if s not in slides:
                    del self._layers[s]
        for key in keys:
            self.request(key)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
