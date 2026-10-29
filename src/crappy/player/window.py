# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""Fullscreen window: keyboard/mouse/clicker input and frame pacing.

Keys
  next      Right, Down, Page Down, Space, N, Enter, left click, wheel down
  previous  Left, Up, Page Up, Backspace, P, right click, wheel up
  1 2 ... Enter    go to slide number
  Home / End       first / last slide
  B or .  black screen        W or ,  white screen     (again to come back)
  F / F11 fullscreen on/off   S  move to the next screen (swap with the presenter view)
  R  reset the presenter timer   + / -  notes text size     Esc / Q  quit
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QScreen, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from crappy.player import scene
from crappy.player.deck import ClipRef, Deck
from crappy.player.images import SlideImages
from crappy.player.movie import MovieDecoder
from crappy.player.timeline import Blend, Pos, Timeline

K = Qt.Key
NEXT_KEYS = {K.Key_Right, K.Key_Down, K.Key_PageDown, K.Key_Space, K.Key_N}
PREV_KEYS = {K.Key_Left, K.Key_Up, K.Key_PageUp, K.Key_Backspace, K.Key_P}
ENTER_KEYS = {K.Key_Return, K.Key_Enter}
CURSOR_HIDE_MS = 2000
# movie frames decoded ahead of the playback position, in the playing direction
LOOKAHEAD = 12


def upcoming_frames(clip: ClipRef, progress: float, direction: int, count: int = LOOKAHEAD) -> list[int]:
    """Movie frames a clip will show next from `progress`, most urgent first.
    Its first and last frames are the slides' own backgrounds: never decoded."""
    k = clip.index(progress)
    indices = (k + direction * i for i in range(count))
    return [clip.frame(i) for i in indices if 0 < i < clip.n_frames - 1]


def fit(width: float, height: float, outer: QRectF) -> QRectF:
    """Largest rectangle of the given aspect ratio centred in `outer` (letterbox)."""
    scale = min(outer.width() / width, outer.height() / height)
    w, h = width * scale, height * scale
    return QRectF(outer.x() + (outer.width() - w) / 2, outer.y() + (outer.height() - h) / 2, w, h)


class Controller:
    """Everything but the widgets: the audience view and the presenter view share it."""

    def __init__(self, deck: Deck, start: Pos | None = None, clock=time.monotonic):
        self.deck = deck
        self.clock = clock
        self.timeline = Timeline(deck, start)
        self.images = SlideImages(deck)
        self.decoders = {mid: MovieDecoder(m.video, m.first) for mid, m in deck.movies.items()}
        self._last_clip_image: dict[ClipRef, object] = {}
        self.clip_frames_shown = 0
        self.clip_frames_late = 0           # shown while the exact frame was not decoded yet
        self.blank: QColor | None = None
        self.typed = ""                  # slide number being typed
        self.started = clock()           # presenter timer
        self.notes_scale = 1.0
        self.views: list = []
        self.request_quit = lambda: None
        self.toggle_fullscreen = lambda: None
        self.next_screen = lambda: None
        self._preload()

    def request_update(self) -> None:
        for view in self.views:
            view.update()

    def elapsed(self) -> float:
        return self.clock() - self.started

    def _preload(self) -> None:
        """Keep ready what the screen shows now and what the next key presses may show."""
        keys = [("composite", p) for p in self.timeline.neighbours()]
        frames: dict[str, list[int]] = {mid: [] for mid in self.decoders}
        moves = [(a, b, effect, d, 0.0 if d > 0 else 1.0) for a, b, effect, d in self.timeline.moves()]
        current = self.timeline.scene(self.clock())
        if isinstance(current, Blend):
            moves.insert(0, (current.a, current.b, current.effect, current.direction, current.progress))
        for a, b, effect, direction, progress in moves:
            if effect.kind == "timeline":
                keys += [("composite", a), ("composite", b), ("background", b.slide)]
                continue
            if effect.clip is None:
                keys += [("composite", a), ("composite", b)]
                continue
            keys += [("background", a.slide), ("background", b.slide), ("overlay", a), ("overlay", b)]
            if effect.clip.movie in frames:
                frames[effect.clip.movie] += upcoming_frames(effect.clip, progress, direction)
        self.images.keep(list(dict.fromkeys(keys)))
        for mid, wanted in frames.items():
            self.decoders[mid].keep(list(dict.fromkeys(wanted)))

    # --- image provider for scene.draw ---------------------------------------

    def composite(self, pos: Pos):
        return self.images.get(pos)

    def overlay(self, pos: Pos):
        return self.images.overlay(pos)

    def slide_info(self, slide: int):
        return self.deck.slides[slide]

    def background(self, slide: int):
        return self.images.background(slide)

    def layers(self, slide: int):
        return self.images.layers(slide)

    @property
    def canvas(self) -> tuple[int, int]:
        return self.deck.size

    def clip_background(self, s: Blend):
        """The movie frame for this progress; never waits for the decoder: when the
        frame is not ready, the closest earlier one (in playing order) is shown."""
        clip = s.effect.clip
        k, last = clip.index(s.progress), clip.n_frames - 1
        if k == 0:
            return self.images.background(s.a.slide)
        if k == last:
            return self.images.background(s.b.slide)
        self.clip_frames_shown += 1
        decoder = self.decoders.get(clip.movie)
        image = None
        if decoder is not None:
            for j in range(0, 30):
                kk = k - s.direction * j
                if not 0 < kk < last:
                    break
                image = decoder.ready(clip.frame(kk))
                if image is not None:
                    if j:
                        self.clip_frames_late += 1
                    break
        if image is None:
            self.clip_frames_late += 1
            image = self._last_clip_image.get(clip) or self.images.background(
                s.a.slide if s.direction > 0 else s.b.slide)
        self._last_clip_image[clip] = image
        return image

    # --- input ---------------------------------------------------------------

    def key(self, key: int, text: str = "") -> bool:
        now = self.clock()
        if text.isdigit():
            self.typed += text
        elif key in ENTER_KEYS and self.typed:
            index = self.deck.index_of_number(int(self.typed))
            self.typed = ""
            if index is not None:
                self.blank = None
                self.timeline.goto(index, now)
        elif key == K.Key_Escape and self.typed:
            self.typed = ""
        elif key == K.Key_Backspace and self.typed:
            self.typed = self.typed[:-1]
        elif key in (K.Key_Escape, K.Key_Q):
            self.request_quit()
            return True
        elif key in (K.Key_B, K.Key_Period):
            self._toggle_blank(QColor("black"))
        elif key in (K.Key_W, K.Key_Comma):
            self._toggle_blank(QColor("white"))
        elif key in (K.Key_F, K.Key_F11):
            self.toggle_fullscreen()
        elif key == K.Key_S:
            self.next_screen()
        elif key == K.Key_R:
            self.started = now
        elif key in (K.Key_Plus, K.Key_Equal):
            self.notes_scale = min(3.0, self.notes_scale * 1.15)
        elif key == K.Key_Minus:
            self.notes_scale = max(0.4, self.notes_scale / 1.15)
        elif key in NEXT_KEYS or key in ENTER_KEYS:
            self.next()
        elif key in PREV_KEYS:
            self.prev()
        elif key == K.Key_Home:
            self.blank = None
            self.timeline.first(now)
        elif key == K.Key_End:
            self.blank = None
            self.timeline.last(now)
        else:
            return False
        self._preload()
        self.request_update()
        return True

    def next(self) -> None:
        if self.blank is not None:          # first key after a blank screen only uncovers it
            self.blank = None
        else:
            self.timeline.next(self.clock())
        self._preload()
        self.request_update()

    def prev(self) -> None:
        if self.blank is not None:
            self.blank = None
        else:
            self.timeline.prev(self.clock())
        self._preload()
        self.request_update()

    def _toggle_blank(self, color: QColor) -> None:
        self.blank = None if self.blank == color else color

    # --- drawing -------------------------------------------------------------

    def paint(self, painter: QPainter, rect: QRectF) -> bool:
        """Draw one frame; returns True while an animation needs more frames."""
        now = self.clock()
        painter.fillRect(rect, QColor("black"))
        if self.blank is not None:
            painter.fillRect(rect, self.blank)
            animating = False
        else:
            target = fit(*self.deck.size, rect)
            current = self.timeline.scene(now)
            scene.draw(painter, target, current, self)
            animating = self.timeline.animating(now)
            self._preload()
        if self.typed:
            self._draw_typed(painter, rect)
        return animating

    def _draw_typed(self, painter: QPainter, rect: QRectF) -> None:
        font = QFont()
        font.setPixelSize(max(16, int(rect.height() / 25)))
        painter.setFont(font)
        box = QRectF(rect.x() + 20, rect.bottom() - font.pixelSize() * 2 - 20, font.pixelSize() * 8,
                     font.pixelSize() * 2)
        painter.fillRect(box, QColor(0, 0, 0, 180))
        painter.setPen(QColor("white"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, f"→ {self.typed}")

    def close(self) -> None:
        self.images.close()
        for d in self.decoders.values():
            d.close()


class _ViewMixin:
    """Input plumbing shared by the audience and presenter widgets."""

    controller: Controller

    def _setup(self, controller: Controller, title: str, hide_cursor: bool = True) -> None:
        self.controller = controller
        controller.views.append(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setWindowTitle(title)
        self._screen = None
        self._hide_cursor = hide_cursor
        self._cursor_timer = QTimer(self, singleShot=True, interval=CURSOR_HIDE_MS)
        if hide_cursor:
            self._cursor_timer.timeout.connect(lambda: self.setCursor(Qt.CursorShape.BlankCursor))
            self._cursor_timer.start()

    def present(self, screen: QScreen, fullscreen: bool = True) -> None:
        """Show on `screen`.

        On Wayland a client cannot position its windows: the screen only counts
        when it is set on the native window (QWindow) before the fullscreen
        request, which then names that output. QWidget.setScreen() before the
        native window exists is ignored, hence create() first.
        """
        self._screen = screen
        self.create()
        self.windowHandle().setScreen(screen)
        if fullscreen:
            self.showFullScreen()
        else:
            self.resize(1280, 720)
            self.show()

    def move_to(self, screen: QScreen) -> None:
        # a mapped Wayland surface stays where the compositor put it: unmap it,
        # so that showing it again sends a new request naming the target output
        fullscreen = self.isFullScreen()
        self.hide()
        self.present(screen, fullscreen)

    @property
    def target_screen(self) -> QScreen | None:
        return self._screen

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            if self._screen is not None:
                self.windowHandle().setScreen(self._screen)
            self.showFullScreen()

    def _frame(self, painter: QPainter) -> None:
        if self.controller.paint(painter, QRectF(self.rect())):
            self.update()           # next frame; throttled by the display's refresh

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self.controller.key(event.key(), event.text()):
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.controller.next()
        elif event.button() == Qt.MouseButton.RightButton:
            self.controller.prev()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.unsetCursor()
        if self._hide_cursor:
            self._cursor_timer.start()

    def wheelEvent(self, event: QWheelEvent) -> None:
        dy = event.angleDelta().y()
        if dy < 0:
            self.controller.next()
        elif dy > 0:
            self.controller.prev()

    def closeEvent(self, event) -> None:
        if self in self.controller.views:
            self.controller.views.remove(self)
        self.controller.request_quit()          # closing either window ends the show
        super().closeEvent(event)


class GLView(_ViewMixin, QOpenGLWidget):
    def __init__(self, controller: Controller):
        super().__init__()
        self._setup(controller, f"CraPPy — {controller.deck.root.name}")

    def paintGL(self) -> None:
        painter = QPainter(self)
        self._frame(painter)
        painter.end()


class RasterView(_ViewMixin, QWidget):
    """Software rendering: for tests, or when OpenGL is unavailable."""

    def __init__(self, controller: Controller):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._setup(controller, f"CraPPy — {controller.deck.root.name}")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        self._frame(painter)
        painter.end()
