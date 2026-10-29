# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

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
    return default_screen(screens, app.primaryScreen())


# connector names of built-in laptop panels
_INTERNAL = ("eDP", "LVDS", "DSI")


def default_screen(screens, primary):
    """A projector is an external output: prefer external screens, and among
    several, one that is not the primary (the desk monitor)."""
    if len(screens) == 1:
        return screens[0]
    external = [s for s in screens if not s.name().startswith(_INTERNAL)]
    candidates = [s for s in external if s != primary] or external or [s for s in screens if s != primary]
    return candidates[0]


def run(manifest: Path, screen: int | None = None, windowed: bool = False, start: int | None = None,
        software: bool = False, presenter: str = "auto", presenter_screen: int | None = None) -> int:
    """presenter: "auto" (when there is a second screen), "on" or "off"."""
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
    audience = (RasterView if software else GLView)(controller)
    audience_screen = _pick_screen(app, screen)

    others = [s for s in app.screens() if s != audience_screen]
    if presenter_screen is not None:
        others = [_pick_screen(app, presenter_screen)]
    show_presenter = presenter == "on" or (presenter == "auto" and others and not windowed)
    view = None
    if show_presenter:
        from crappy.player.presenter import PresenterView
        view = PresenterView(controller)
        # alone on one screen (rehearsal), both views are windows
        view.present(others[0] if others else audience_screen, fullscreen=bool(others) and not windowed)
    audience.present(audience_screen, fullscreen=not windowed)

    def next_screen() -> None:
        screens = app.screens()
        if view is not None and view.target_screen in screens and view.target_screen != audience.target_screen:
            # two views on two screens: swap them
            a, p = audience.target_screen, view.target_screen
            audience.move_to(p)
            view.move_to(a)
            return
        i = screens.index(audience.target_screen) if audience.target_screen in screens else 0
        audience.move_to(screens[(i + 1) % len(screens)])

    controller.request_quit = app.quit
    controller.toggle_fullscreen = audience.toggle_fullscreen
    controller.next_screen = next_screen
    try:
        return app.exec()
    finally:
        controller.close()
