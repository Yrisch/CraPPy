# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""Presenter view: current slide (live), what the next key shows, notes, timer.

    ┌──────────────────────────────────────────────────────────────┐
    │ Slide 3 / 15 · click 2 / 6   next: clip 1.5 s  elapsed 12:04 clock 14:05│
    ├───────────────────────────────────────┬──────────────────────┤
    │                                       │ next                 │
    │            current slide              ├──────────────────────┤
    │       (transitions play here too)     │ notes                │
    └───────────────────────────────────────┴──────────────────────┘
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from crappy.player import scene
from crappy.player.deck import Effect
from crappy.player.timeline import Blend
from crappy.player.window import Controller, _ViewMixin, fit

BACKGROUND = QColor("#1b1b1b")
FRAME = QColor("#3a3a3a")
TEXT = QColor("#e8e8e8")
DIM = QColor("#9a9a9a")
ACCENT = QColor("#f0a030")


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def describe(effect: Effect) -> str:
    if effect.instant:
        return "cut"
    if effect.kind == "clip" and effect.clip is not None:
        return f"clip {effect.duration:.1f} s"
    side = f" {effect.side}" if effect.side else ""
    return f"{effect.kind.replace('_', ' ')}{side} {effect.duration:.1f} s"


def _font(painter: QPainter, pixels: float, bold: bool = False) -> QFont:
    font = QFont()
    font.setPixelSize(max(9, int(pixels)))
    font.setBold(bold)
    painter.setFont(font)
    return font


def paint_presenter(painter: QPainter, rect: QRectF, c: Controller, wall_clock=time.localtime) -> bool:
    """Draw the presenter view; returns True while an animation needs more frames."""
    now = c.clock()
    painter.fillRect(rect, BACKGROUND)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    W, H = rect.width(), rect.height()
    m = H * 0.02
    bar = H * 0.07
    deck, tl = c.deck, c.timeline

    current = tl.scene(now)
    animating = tl.animating(now)
    # where the talk is (or is going), and what the next key press will show from there
    if isinstance(current, Blend):
        here = current.b if current.direction > 0 else current.a
    else:
        here = current.pos
    upcoming = tl.forward_from(here)
    slide = deck.slides[here.slide]

    # --- top bar ---------------------------------------------------------------
    last_number = max(s.number for s in deck.slides if not s.hidden)
    status = f"Slide {slide.number} / {last_number}"
    if slide.n_steps > 1:
        status += f"   ·   click {here.step + 1} / {slide.n_steps}"
    _font(painter, bar * 0.45, bold=True)
    painter.setPen(TEXT)
    painter.drawText(QRectF(rect.x() + m, rect.y(), W * 0.4, bar), Qt.AlignmentFlag.AlignVCenter, status)

    if upcoming is None:
        nxt_text = "end of the talk"
    else:
        target, effect = upcoming
        what = "click" if target.slide == here.slide else f"slide {deck.slides[target.slide].number}"
        nxt_text = f"next: {what}  ({describe(effect)})"
    _font(painter, bar * 0.38)
    painter.setPen(DIM)
    painter.drawText(QRectF(rect.x() + W * 0.35, rect.y(), W * 0.35, bar),
                     Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter, nxt_text)

    # right: "elapsed 12:04   clock 14:05"
    x = rect.right() - m
    for caption, value, color in (("clock", time.strftime("%H:%M", wall_clock()), TEXT),
                                  ("elapsed", format_elapsed(c.elapsed()), ACCENT)):
        for text, size, bold, pen in ((value, 0.5, True, color), (caption + " ", 0.3, False, DIM)):
            metrics = QFontMetricsF(_font(painter, bar * size, bold))
            width = metrics.horizontalAdvance(text)
            painter.setPen(pen)
            painter.drawText(QRectF(x - width, rect.y(), width, bar), Qt.AlignmentFlag.AlignVCenter, text)
            x -= width
        x -= bar * 0.6

    # --- current slide -------------------------------------------------------------
    top = rect.y() + bar
    left_w = (W - 3 * m) * 0.62
    cur_box = fit(*deck.size, QRectF(rect.x() + m, top, left_w, H - bar - m))
    cur_box.moveTop(top)
    painter.fillRect(cur_box.adjusted(-2, -2, 2, 2), FRAME)
    painter.fillRect(cur_box, QColor("black"))
    scene.draw(painter, cur_box, current, c)
    if c.blank is not None:
        painter.fillRect(cur_box, QColor(0, 0, 0, 150))
        _font(painter, cur_box.height() * 0.06, bold=True)
        painter.setPen(ACCENT)
        label = "audience sees a black screen" if c.blank == QColor("black") else "audience sees a white screen"
        painter.drawText(cur_box, Qt.AlignmentFlag.AlignCenter, label)
    if c.typed:
        _font(painter, cur_box.height() * 0.08, bold=True)
        painter.setPen(ACCENT)
        painter.drawText(cur_box.adjusted(m, m, -m, -m), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                         f"go to slide {c.typed}…")

    # --- next ----------------------------------------------------------------------
    right_x = cur_box.right() + m
    right_w = rect.right() - m - right_x
    _font(painter, bar * 0.32)
    painter.setPen(DIM)
    painter.drawText(QRectF(right_x, top - bar * 0.05, right_w, bar * 0.4), Qt.AlignmentFlag.AlignBottom, "NEXT")
    nxt_box = fit(*deck.size, QRectF(right_x, top + bar * 0.4, right_w, H))
    nxt_box.moveTop(top + bar * 0.4)
    painter.fillRect(nxt_box.adjusted(-2, -2, 2, 2), FRAME)
    if upcoming is None:
        painter.fillRect(nxt_box, QColor("black"))
        _font(painter, nxt_box.height() * 0.1)
        painter.setPen(DIM)
        painter.drawText(nxt_box, Qt.AlignmentFlag.AlignCenter, "end")
    else:
        painter.drawImage(nxt_box, c.composite(tl.settled(upcoming[0])))

    # --- notes ---------------------------------------------------------------------
    notes_box = QRectF(right_x, nxt_box.bottom() + m, right_w, rect.bottom() - m - nxt_box.bottom() - m)
    _font(painter, bar * 0.32)
    painter.setPen(DIM)
    painter.drawText(QRectF(notes_box.x(), notes_box.y(), right_w, bar * 0.4), Qt.AlignmentFlag.AlignTop, "NOTES")
    _font(painter, H * 0.028 * c.notes_scale)
    painter.setPen(TEXT)
    painter.drawText(notes_box.adjusted(0, bar * 0.45, 0, 0),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                     slide.notes or "—")
    return animating


class PresenterView(_ViewMixin, QOpenGLWidget):
    def __init__(self, controller: Controller):
        super().__init__()
        self._setup(controller, f"CraPPy presenter — {controller.deck.root.name}", hide_cursor=False)
        self._tick = QTimer(self, interval=500)       # clock and timer
        self._tick.timeout.connect(self.update)
        self._tick.start()

    def paintGL(self) -> None:
        painter = QPainter(self)
        animating = paint_presenter(painter, QRectF(self.rect()), self.controller)
        painter.end()
        if animating:
            self.update()
