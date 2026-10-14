"""Drawing a Still or a Blend with a QPainter, inside a target rectangle.

Transitions work on whole composited slides A and B:
  fade        A, then B with opacity p
  fade_color  A fading into the colour, then the colour fading into B
  push        B enters from `side` while A leaves on the opposite side
  cover       B slides in from `side` over a still A
  uncover     A slides out towards `side`, revealing a still B
  wipe        B is revealed by an edge moving away from `side`
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from crappy.player.timeline import Blend, Still

# unit vector pointing from the centre of the screen towards a side
_SIDE = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}


def _smooth(p: float) -> float:
    """Ease in-out for movements (fades stay linear)."""
    return p * p * (3 - 2 * p)


def draw(painter: QPainter, target: QRectF, scene: Still | Blend, image_for) -> None:
    """image_for(pos) -> QImage of that position, already composited."""
    painter.save()
    painter.setClipRect(target)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if isinstance(scene, Still):
        painter.drawImage(target, image_for(scene.pos))
    else:
        _draw_blend(painter, target, scene, image_for(scene.a), image_for(scene.b))
    painter.restore()


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

