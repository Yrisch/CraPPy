"""`crappy play`: open the player on a built talk."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from crappy.player.deck import Deck
from crappy.player.timeline import Pos
from crappy.player.window import Controller, GLView, RasterView


def screens_summary() -> list[str]:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    primary = app.primaryScreen()
    return [f"{i}: {s.name()} {s.geometry().width()}x{s.geometry().height()}"
            f"{' (primary)' if s == primary else ''}" for i, s in enumerate(app.screens())]


def _pick_screen(app: QGuiApplication, index: int | None):
    screens = app.screens()
    if index is not None:
        if not 0 <= index < len(screens):
            raise SystemExit(f"error: no screen {index}; screens: {screens_summary()}")
        return screens[index]
    # a projector is usually the screen that is not the primary one
    others = [s for s in screens if s != app.primaryScreen()]
    return others[0] if others else app.primaryScreen()


def run(manifest: Path, screen: int | None = None, windowed: bool = False, start: int | None = None,
        software: bool = False) -> int:
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSwapInterval(1)              # one frame per display refresh
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("crappy")

    deck = Deck.load(manifest)
    start_pos = None
    if start is not None:
        index = deck.index_of_number(start)
        if index is None:
            raise SystemExit(f"error: no slide {start}")
        start_pos = Pos(index, 0)
    controller = Controller(deck, start_pos)
    view = (RasterView if software else GLView)(controller)

    view.setScreen(_pick_screen(app, screen))
    if windowed:
        view.resize(1280, 720)
        view.show()
    else:
        view.showFullScreen()
    return app.exec()
