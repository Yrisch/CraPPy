# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""Decoding movie frames for clip transitions.

Movies are all-intra H.264 (see crappy.movie): every frame decodes on its own,
so the compressed frames are kept in memory and any of them is decoded on
demand, in whichever order playback needs (forwards, backwards, turning
around). Decoding happens in worker threads (PyAV releases the GIL), one
codec context per thread.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import av
from PySide6.QtGui import QImage


class MovieDecoder:
    def __init__(self, path: Path, first: int, workers: int = 2, slice_threads: int = 4):
        """first: movie frame number of the video's first frame."""
        self.first = first
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            self._extradata = stream.codec_context.extradata
            self._packets = [bytes(p) for p in container.demux(stream) if p.size]
        self._slice_threads = slice_threads
        self._local = threading.local()
        self._pool = ThreadPoolExecutor(workers, thread_name_prefix="crappy-movie")
        self._jobs: dict[int, Future[QImage]] = {}

    def __contains__(self, frame: int) -> bool:
        return 0 <= frame - self.first < len(self._packets)

    def _codec(self):
        ctx = getattr(self._local, "ctx", None)
        if ctx is None:
            ctx = av.CodecContext.create("h264", "r")
            ctx.extradata = self._extradata
            ctx.thread_type = "SLICE"
            ctx.thread_count = self._slice_threads
            self._local.ctx = ctx
        return ctx

    def _decode(self, frame: int) -> QImage:
        frames = self._codec().decode(av.Packet(self._packets[frame - self.first]))
        if not frames:
            raise RuntimeError(f"no picture decoded for frame {frame}")
        pixels = frames[0].to_ndarray(format="bgra")       # = QImage RGB32 byte order
        h, w = pixels.shape[:2]
        return QImage(pixels.data, w, h, pixels.strides[0], QImage.Format.Format_RGB32).copy()

    def request(self, frame: int) -> Future[QImage] | None:
        if frame not in self:
            return None
        job = self._jobs.get(frame)
        if job is None:
            job = self._jobs[frame] = self._pool.submit(self._decode, frame)
        return job

    def ready(self, frame: int) -> QImage | None:
        job = self._jobs.get(frame)
        if job is not None and job.done() and not job.cancelled() and job.exception() is None:
            return job.result()
        return None

    def keep(self, frames: list[int]) -> None:
        """Decode these frames, most urgent first, and drop every other one."""
        wanted = set(frames)
        for f in list(self._jobs):
            if f not in wanted:
                self._jobs.pop(f).cancel()
        for f in frames:
            self.request(f)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
