"""LibreOffice -> PDF -> pixels."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium

# Lossless, full-resolution images, hidden slides kept so PDF pages map to slide indices.
_PDF_OPTIONS = {
    "UseLosslessCompression": {"type": "boolean", "value": "true"},
    "ReduceImageResolution": {"type": "boolean", "value": "false"},
    "ExportHiddenSlides": {"type": "boolean", "value": "true"},
    "ExportNotesPages": {"type": "boolean", "value": "false"},
}


class RenderError(RuntimeError):
    pass


@dataclass
class ExportJob:
    odp: Path
    pages: list[int] | None = None   # 1-based slide numbers, None = all

    @property
    def pdf(self) -> Path:
        return self.odp.with_suffix(".pdf")


def find_soffice() -> str:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    raise RenderError("LibreOffice (soffice) not found in PATH")


def _export_one(job: ExportJob, profile: Path, soffice: str) -> Path:
    options = dict(_PDF_OPTIONS)
    if job.pages is not None:
        options["PageRange"] = {"type": "string", "value": ",".join(map(str, job.pages))}
    job.pdf.unlink(missing_ok=True)
    cmd = [
        soffice,
        # a private profile: otherwise a LibreOffice already open on the desktop
        # receives the request and the conversion silently does nothing
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--headless", "--norestore",
        "--convert-to", "pdf:impress_pdf_Export:" + json.dumps(options),
        "--outdir", str(job.pdf.parent), str(job.odp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not job.pdf.exists():
        raise RenderError(f"LibreOffice failed on {job.odp.name}:\n{proc.stdout}\n{proc.stderr}")
    return job.pdf


def export_pdfs(jobs: list[ExportJob], profiles_dir: Path, workers: int | None = None, progress=None) -> None:
    """Convert every job's .odp to PDF, running several LibreOffice instances in parallel."""
    soffice = find_soffice()
    workers = max(1, min(workers or min(8, max(1, (os.cpu_count() or 2) // 2)), len(jobs)))
    slots: queue.Queue[Path] = queue.Queue()
    for i in range(workers):
        slots.put(profiles_dir / f"worker{i}")

    def run(job: ExportJob) -> Path:
        profile = slots.get()
        try:
            return _export_one(job, profile, soffice)
        finally:
            slots.put(profile)
            if progress:
                progress(job)

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(run, jobs))


class PdfRaster:
    """Pages of a PDF rendered on demand to (H, W, 3) uint8, fitted and centred in `size`."""

    def __init__(self, pdf: Path, size: tuple[int, int]):
        self.size = size
        self.doc = pdfium.PdfDocument(str(pdf))

    def __len__(self) -> int:
        return len(self.doc)

    def __getitem__(self, index: int) -> np.ndarray:
        width, height = self.size
        page = self.doc[index]
        w_pt, h_pt = page.get_size()
        scale = min(width / w_pt, height / h_pt)
        img = page.render(scale=scale, fill_color=(255, 255, 255, 255), rev_byteorder=True).to_numpy()[..., :3]
        canvas = np.zeros((height, width, 3), np.uint8)
        h, w = min(img.shape[0], height), min(img.shape[1], width)
        y0, x0 = (height - h) // 2, (width - w) // 2
        canvas[y0:y0 + h, x0:x0 + w] = img[:h, :w]
        return canvas

    def close(self) -> None:
        self.doc.close()
