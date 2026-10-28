"""`crappy preview`: composite every slide/step of a build into plain images."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from crappy.matte import over
from crappy.player.animate import layer_states
from crappy.player.deck import Deck


def _load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path))


def compose(slide, step: int, size: tuple[int, int]) -> np.ndarray:
    """Background + layers as they are at the end of a click step (RGB uint8)."""
    w, h = size
    frame = _load(slide.background)[..., :3]
    for layer, (opacity, dx, dy) in zip(slide.layers, layer_states(slide, step)):
        if opacity <= 0:
            continue
        pixels = _load(layer.path).copy()
        x, y = layer.x + round(dx), layer.y + round(dy)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + pixels.shape[1]), min(h, y + pixels.shape[0])
        if x1 <= x0 or y1 <= y0:
            continue
        part = pixels[y0 - y:y1 - y, x0 - x:x1 - x]
        if opacity < 1:
            part[..., 3] = (part[..., 3] * opacity).astype(np.uint8)
        frame = frame.copy()
        frame[y0:y1, x0:x1] = over(part, frame[y0:y1, x0:x1])
    return frame


def write_previews(manifest: dict, out_dir: Path, thumb_width: int = 480, columns: int = 4) -> Path:
    """Writes preview/NNN_sK.png for every step and preview/contact_sheet.png."""
    preview = out_dir / "preview"
    preview.mkdir(exist_ok=True)
    for old in preview.glob("*.png"):
        old.unlink()
    tiles = []
    deck = Deck.load(out_dir / "manifest.json")
    for s, slide in zip(manifest["slides"], deck.slides):
        for k, step in enumerate(slide.steps):
            frame = compose(slide, k, deck.size)
            Image.fromarray(frame).save(preview / f"{s['number']:03d}_s{k}.png")
            label = f"{s['number']}.{k}  {s['name'][:40]}" + ("  [hidden]" if s["hidden"] else "")
            if k == 0 and s["transition"]["kind"] != "cut":
                label += f"  <- {s['transition']['kind']}"
            elif k > 0:
                label += "  <- auto" if step.auto else "  <- click"
                if step.duration > 0:
                    label += f" ({step.duration:.1f} s)"
            tiles.append((frame, label))

    w, h = manifest["size"]
    tw, th = thumb_width, round(thumb_width * h / w)
    pad, text_h = 8, 18
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (tw + pad) + pad, rows * (th + text_h + pad) + pad), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)
    for i, (frame, label) in enumerate(tiles):
        x = pad + (i % columns) * (tw + pad)
        y = pad + (i // columns) * (th + text_h + pad)
        sheet.paste(Image.fromarray(frame).resize((tw, th), Image.Resampling.LANCZOS), (x, y + text_h))
        draw.text((x, y + 2), label, fill=(230, 230, 230))
    path = preview / "contact_sheet.png"
    sheet.save(path)
    return path
