"""Encoding frame sequences for the player.

H.264 with every frame a keyframe (all-intra): any frame decodes on its own,
so playing backwards, turning around or jumping costs nothing more than
playing forwards. Full chroma (4:4:4) keeps colour maps sharp; 'fastdecode'
and 8 slices per frame let a 1080p frame decode in ~5 ms on 8 threads. At
CRF 14 the frames are visually lossless (~47-50 dB PSNR on simulation renders).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

ENCODER = "x264 all-intra yuv444p crf14 fastdecode slices8 v1"
_X264 = ["-c:v", "libx264", "-preset", "fast", "-tune", "fastdecode", "-crf", "14",
         "-g", "1", "-x264-params", "slices=8", "-pix_fmt", "yuv444p", "-an"]


class EncodeError(RuntimeError):
    pass


def source_key(sources: list[Path], fps: float, size: tuple[int, int]) -> str:
    """Changes when any source file, the frame rate, the size or the encoder settings change."""
    h = hashlib.sha256(f"{ENCODER}|{fps}|{size}".encode())
    for p in sources:
        st = p.stat()
        h.update(f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:20]


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise EncodeError("ffmpeg not found in PATH (needed to encode movie clips)")
    return path


def _fit(size: tuple[int, int]) -> str:
    w, h = size
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")


def encode_frames(frames: list[Path], out: Path, fps: float, size: tuple[int, int]) -> None:
    """Image files (any format ffmpeg reads, in this order) -> out (.mp4)."""
    tmp = out.with_suffix(".part.mp4")
    cmd = [_ffmpeg(), "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
           "-vf", _fit(size), *_X264, str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in frames:
            proc.stdin.write(f.read_bytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise EncodeError(f"ffmpeg failed encoding {frames[0].parent}:\n{err}")
    tmp.replace(out)


def encode_video(video: Path, out: Path, size: tuple[int, int]) -> None:
    tmp = out.with_suffix(".part.mp4")
    cmd = [_ffmpeg(), "-loglevel", "error", "-y", "-i", str(video), "-vf", _fit(size), *_X264, str(tmp)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise EncodeError(f"ffmpeg failed encoding {video}:\n{proc.stderr}")
    tmp.replace(out)


def frame_count(video: Path) -> int:
    import av
    with av.open(str(video)) as c:
        return sum(1 for p in c.demux(c.streams.video[0]) if p.size)
