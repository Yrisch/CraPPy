"""Difference matting: recover a transparent layer from renders over two backdrops.

A pixel of colour C and opacity a renders over a backdrop b as
R = a*C + (1 - a)*b. With two renders R1, R2 over backdrops b1, b2:
R1 - R2 = (1 - a)(b1 - b2), which gives a (least squares over the channels),
then C = (R1 - (1 - a)*b1) / a. This is exact for anything LibreOffice draws
(anti-aliasing, transparency, gradients, shadows), as long as both renders are
identical apart from the backdrop.
"""

from __future__ import annotations

import numpy as np


def unmatte(r1: np.ndarray, r2: np.ndarray, b1, b2) -> np.ndarray:
    """(H, W, 3) uint8 renders over RGB backdrops b1, b2 -> (H, W, 4) uint8 RGBA, straight alpha."""
    r1 = r1.astype(np.float32) / 255
    r2 = r2.astype(np.float32) / 255
    b1 = np.asarray(b1, np.float32) / 255
    b2 = np.asarray(b2, np.float32) / 255
    d = b1 - b2
    transparency = np.clip((r1 - r2) @ d / (d @ d), 0, 1)
    alpha = 1 - transparency
    premultiplied = r1 - transparency[..., None] * b1
    rgb = np.clip(premultiplied / np.maximum(alpha, 1 / 255)[..., None], 0, 1)
    rgb[alpha < 1 / 512] = 0
    return (np.dstack([rgb, alpha]) * 255).round().astype(np.uint8)


def over(layer: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Composite an RGBA layer over an RGB background (both uint8)."""
    a = layer[..., 3:4].astype(np.float32) / 255
    out = layer[..., :3].astype(np.float32) * a + background[..., :3].astype(np.float32) * (1 - a)
    return out.round().astype(np.uint8)
