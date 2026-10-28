"""Drawing a Still or a Blend with a QPainter, inside a target rectangle.

Transitions work on whole composited slides A and B:
  fade        A, then B with opacity p
  fade_color  A fading into the colour, then the colour fading into B
  push        B enters from `side` while A leaves on the opposite side
  cover       B slides in from `side` over a still A
  uncover     A slides out towards `side`, revealing a still B
  wipe        B is revealed by an edge moving away from `side`
  clip        the movie plays as background; A's content fades out at the start,
              B's content fades in at the end

  timeline    a click step playing: each animated object shown, faded or moved
              following its effects

`images` provides: composite(pos) (background + layers), overlay(pos),
clip_background(blend) (the movie frame to show, never blocking), and for
timelines slide_info(i), background(i), layers(i) and canvas (size in pixels).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from crappy.player.animate import layer_states
from crappy.player.images import paint_layers
from crappy.player.timeline import Blend, Still

# unit vector pointing from the centre of the screen towards a side
_SIDE = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}


def _smooth(p: float) -> float:
    """Ease in-out for movements (fades stay linear)."""
    return p * p * (3 - 2 * p)


def draw(painter: QPainter, target: QRectF, scene: Still | Blend, images) -> None:
    painter.save()
    painter.setClipRect(target)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if isinstance(scene, Still):
        painter.drawImage(target, images.composite(scene.pos))
    elif scene.effect.kind == "clip" and scene.effect.clip is not None:
        _draw_clip(painter, target, scene, images)
    elif scene.effect.kind == "timeline":
        _draw_timeline(painter, target, scene, images)
    else:
        _draw_blend(painter, target, scene, images.composite(scene.a), images.composite(scene.b))
    painter.restore()


def _draw_timeline(painter: QPainter, r: QRectF, s: Blend, images) -> None:
    pos = s.b                                   # the step being played (same slide as s.a)
    slide = images.slide_info(pos.slide)
    t = s.progress * slide.steps[pos.step].duration
    painter.drawImage(r, images.background(pos.slide))
    paint_layers(painter, images.layers(pos.slide), slide, layer_states(slide, pos.step, t),
                 r.width() / images.canvas[0], r.topLeft())


def _draw_clip(painter: QPainter, r: QRectF, s: Blend, images) -> None:
    painter.drawImage(r, images.clip_background(s))
    alpha_a, alpha_b = s.effect.clip.overlay_alphas(s.progress)
    for pos, alpha in ((s.a, alpha_a), (s.b, alpha_b)):
        if alpha > 0:
            painter.setOpacity(alpha)
            painter.drawImage(r, images.overlay(pos))
    painter.setOpacity(1.0)


def _draw_blend(painter: QPainter, r: QRectF, s: Blend, a: QImage, b: QImage) -> None:
    e, p = s.effect, s.progress
    kind = e.kind
    if kind in ("push", "cover", "uncover") and e.side in _SIDE:
        dx, dy = _SIDE[e.side]
        step = QPointF(dx * r.width(), dy * r.height())
        m = _smooth(p)
        if kind == "push":            # B comes from `side`, A goes the other way
            painter.drawImage(r.translated(-step * m), a)
            painter.drawImage(r.translated(step * (1 - m)), b)
        elif kind == "cover":
            painter.drawImage(r, a)
            painter.drawImage(r.translated(step * (1 - m)), b)
        else:                         # uncover: A leaves towards `side`
            painter.drawImage(r, b)
            painter.drawImage(r.translated(step * m), a)
    elif kind == "wipe" and e.side in _SIDE:
        painter.drawImage(r, a)
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        reveal = {"left": QRectF(x, y, w * p, h), "right": QRectF(x + w * (1 - p), y, w * p, h),
                  "top": QRectF(x, y, w, h * p), "bottom": QRectF(x, y + h * (1 - p), w, h * p)}[e.side]
        painter.setClipRect(reveal, Qt.ClipOperation.IntersectClip)
        painter.drawImage(r, b)
    elif kind == "fade_color":
        color = QColor(e.color or "#000000")
        if p < 0.5:
            painter.drawImage(r, a)
            color.setAlphaF(2 * p)
        else:
            painter.drawImage(r, b)
            color.setAlphaF(2 * (1 - p))
        painter.fillRect(r, color)
    else:                             # fade, and anything unknown
        painter.drawImage(r, a)
        painter.setOpacity(p)
        painter.drawImage(r, b)
        painter.setOpacity(1.0)

