"""`crappy preview`: composite every slide/step of a build into plain images."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from crappy.matte import over


def _load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path))


def write_previews(manifest: dict, out_dir: Path, thumb_width: int = 480, columns: int = 4) -> Path:
    """Writes preview/NNN_sK.png for every step and preview/contact_sheet.png."""
    preview = out_dir / "preview"
    preview.mkdir(exist_ok=True)
    for old in preview.glob("*.png"):
        old.unlink()
    tiles = []
    for s in manifest["slides"]:
        background = _load(out_dir / s["background"])
        for k, step in enumerate(s["steps"]):
            frame = over(_load(out_dir / step["overlay"]), background)
            Image.fromarray(frame).save(preview / f"{s['number']:03d}_s{k}.png")
            label = f"{s['number']}.{k}  {s['name'][:40]}" + ("  [hidden]" if s["hidden"] else "")
            if k == 0 and s["transition"]["kind"] != "cut":
                label += f"  <- {s['transition']['kind']}"
            elif k > 0:
                label += f"  <- click ({step['effect']['kind']})"
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
