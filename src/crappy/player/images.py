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


class SlideImages:
    def __init__(self, deck: Deck, workers: int = 3):
        self.deck = deck
        self._pool = ThreadPoolExecutor(workers, thread_name_prefix="crappy-images")
        self._jobs: dict[Pos, Future[QImage]] = {}

    def request(self, pos: Pos) -> Future[QImage]:
        job = self._jobs.get(pos)
        if job is None:
            slide = self.deck.slides[pos.slide]
            job = self._pool.submit(compose, slide.background, slide.overlays[pos.step])
            self._jobs[pos] = job
        return job

    def get(self, pos: Pos) -> QImage:
        return self.request(pos).result()

    def keep(self, positions: list[Pos]) -> None:
        """Preload these positions and forget the others."""
        wanted = set(positions)
        for pos in list(self._jobs):
            if pos not in wanted:
                self._jobs.pop(pos).cancel()
        for pos in positions:
            self.request(pos)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
