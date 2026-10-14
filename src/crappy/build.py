"""`crappy build`: an .odp -> per-slide background + per-step transparent overlays.

Render passes (each one a whole-document LibreOffice PDF export, run in parallel):
  reference        the untouched talk: self-check of every rebuilt slide
  background       objects removed: what Impress draws as background
  step k / pair i  slides frozen at click step k over backdrop i of their pair
                   (crappy.background.BACKDROPS) -> difference matting.
                   Steps k > 0 only export the slides that have that many steps.

A slide whose rebuild does not match the reference is retried with the other
backdrop pair (its background was classified on the wrong side of
LibreOffice's dark/light threshold).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from crappy import __version__, movie
from crappy.animations import SlideAnimation, parse_slide_animation
from crappy.background import BACKDROPS, BackgroundImage, background_class, background_image, hex_to_rgb, other_class
from crappy.config import Config, config_path_for, load_config
from crappy.matte import over, unmatte
from crappy.odf import NS, OdfPackage, attr, plain_text
from crappy.render import ExportJob, PdfRaster, export_pdfs
from crappy.transitions import Transition, parse_transition
from crappy.variants import StepHider, set_page_backdrops, strip_to_background

MANIFEST = "manifest.json"
FORMAT_VERSION = 1
# self-check: a pixel "differs" from LibreOffice's own render above this level (0-255),
# and a slide fails when more than this fraction of its pixels differ
CHECK_TOLERANCE = 24
CHECK_MAX_FRACTION = 1e-3


@dataclass
class ClipPlan:
    """A transition played from an encoded movie, frames start -> end (end < start: backwards)."""
    movie: str
    start: int
    end: int                         # -1 until known (whole video file given in the side file)
    fps: float
    overlay_in: float
    overlay_out: float
    source: str                      # "movie" (deduced from backgrounds) or "config"

    @property
    def duration(self) -> float:
        return abs(self.end - self.start) / self.fps


@dataclass
class MovieSource:
    id: str
    fps: float
    frames: list[Path] = field(default_factory=list)
    video: Path | None = None


@dataclass
class SlideInfo:
    number: int                      # 1-based, as shown by Impress
    name: str
    hidden: bool
    notes: str
    animation: SlideAnimation
    transition: Transition
    background_image: BackgroundImage | None = None
    movie_frame: tuple[str, int] | None = None     # (movie id, frame index) of the background
    clip: ClipPlan | None = None
    overridden: bool = False         # transition set in the side file
    warnings: list[str] = field(default_factory=list)


@dataclass
class Analysis:
    slides: list[SlideInfo]
    movies: dict[str, MovieSource]
    warnings: list[str]


@dataclass
class Rebuilt:
    background_class: str
    overlays: list[np.ndarray]
    mismatch: float | None           # None when the slide cannot be checked (exit effects)


def default_output_dir(odp: Path) -> Path:
    return odp.with_name(odp.stem + ".crappy")


def analyse(pkg: OdfPackage, cfg: Config) -> Analysis:
    """Everything that can be known without rendering."""
    slides, warnings = [], []
    for i, page in enumerate(pkg.pages(), start=1):
        style, _ = pkg.find_style("style:style", attr(page, "draw:style-name", ""))
        props = None if style is None else style.find("style:drawing-page-properties", NS)
        notes_frame = page.find("presentation:notes/draw:frame[@presentation:class='notes']", NS)
        transition, t_warn = parse_transition(pkg, page)
        anim = parse_slide_animation(page)
        slides.append(SlideInfo(
            number=i,
            name=attr(page, "draw:name", f"page{i}"),
            hidden=props is not None and attr(props, "presentation:visibility") == "hidden",
            notes="" if notes_frame is None else plain_text(notes_frame),
            animation=anim,
            transition=transition,
            background_image=background_image(pkg, page),
            warnings=t_warn + anim.warnings,
        ))

    movies = {f"movie{i}": MovieSource(f"movie{i}", m.fps, frames=m.frames) for i, m in enumerate(cfg.movies)}
    frame_of_stem: dict[str, tuple[str, int]] = {}
    for i, m in reversed(list(enumerate(cfg.movies))):      # the first movie wins on a name clash
        frame_of_stem.update({stem: (f"movie{i}", k) for stem, k in m.index_of_stem().items()})
    for s in slides:
        if s.background_image is not None:
            s.movie_frame = frame_of_stem.get(s.background_image.name)

    by_key = {s.name: s for s in slides} | {str(s.number): s for s in slides}
    for key in list(cfg.clips) + list(cfg.overrides):
        if key not in by_key:
            warnings.append(f"config: no slide named {key!r} (slide names: {[s.name for s in slides]})")
    for key, clip in cfg.clips.items():
        if key in by_key:
            s = by_key[key]
            mid = f"clip{s.number}"
            movies[mid] = MovieSource(mid, clip.fps, frames=clip.frames, video=clip.clip)
            end = len(clip.frames) - 1 if clip.frames else -1
            s.clip = ClipPlan(mid, 0, end, clip.fps, clip.overlay_in, clip.overlay_out, "config")
    for key, o in cfg.overrides.items():
        if key in by_key:
            s = by_key[key]
            t = s.transition
            t.kind = o.kind or t.kind
            t.duration = o.duration if o.duration is not None else (t.duration or 1.0)
            t.side, t.color, t.source = o.side or t.side, o.color or t.color, "config"
            s.overridden = True

    # Between two consecutive (visible) slides whose backgrounds are frames of the
    # same movie, the transition plays the movie from one frame to the other.
    previous = None
    for s in slides:
        if s.hidden:
            continue
        if (previous is not None and s.clip is None and not s.overridden
                and s.movie_frame and previous.movie_frame
                and s.movie_frame[0] == previous.movie_frame[0] and s.movie_frame[1] != previous.movie_frame[1]):
            m = cfg.movies[int(s.movie_frame[0].removeprefix("movie"))]
            s.clip = ClipPlan(s.movie_frame[0], previous.movie_frame[1], s.movie_frame[1],
                              m.fps, m.overlay_in, m.overlay_out, "movie")
        previous = s
    return Analysis(slides, movies, warnings)


def _source_key(odp: Path, cfg: Config, size: tuple[int, int]) -> str:
    h = hashlib.sha256()
    h.update(f"{__version__}|{FORMAT_VERSION}|{size}".encode())
    h.update(odp.read_bytes())
    if cfg.path and cfg.path.exists():
        h.update(cfg.path.read_bytes())
    for p in cfg.media_files():           # re-rendered frames must trigger a rebuild
        st = p.stat()
        h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()


def _encode_movies(analysis: Analysis, movies_dir: Path, size, log) -> dict[str, dict]:
    """Encode the span of each movie that transitions use; returns manifest entries.

    Results are cached by content key, so an unchanged movie is never re-encoded.
    """
    movies_dir.mkdir(parents=True, exist_ok=True)
    spans: dict[str, list[int]] = {}
    for s in analysis.slides:
        if s.clip is not None:
            spans.setdefault(s.clip.movie, []).extend(i for i in (s.clip.start, s.clip.end) if i >= 0)
    entries, keep = {}, set()
    for mid, frames_used in spans.items():
        src = analysis.movies[mid]
        if src.video is not None:
            key = movie.source_key([src.video], src.fps, size)
            out = movies_dir / f"{mid}-{key}.mp4"
            if not out.exists():
                log(f"  encoding {src.video.name}")
                movie.encode_video(src.video, out, size)
            first, count = 0, movie.frame_count(out)
        else:
            first, last = min(frames_used), max(frames_used)
            frames = src.frames[first:last + 1]
            key = movie.source_key(frames, src.fps, size)
            out = movies_dir / f"{mid}-{key}.mp4"
            if not out.exists():
                log(f"  encoding {len(frames)} frames of {frames[0].parent.name}/ ({frames[0].name} - {frames[-1].name})")
                t = time.monotonic()
                movie.encode_frames(frames, out, src.fps, size)
                log(f"  encoded {mid} in {time.monotonic() - t:.1f} s")
            count = len(frames)
        keep.add(out.name)
        entries[mid] = {"video": str(out.relative_to(movies_dir.parent)), "first": first, "count": count,
                        "fps": src.fps}
    for stale in movies_dir.glob("*.mp4"):
        if stale.name not in keep:
            stale.unlink()
    return entries


def _original_background(s: SlideInfo, size) -> np.ndarray | None:
    """A stretched picture background, straight from the .odp: pixel-exact, unlike
    LibreOffice's PDF render of it (resampled), so that movie clips end on it seamlessly."""
    bg = s.background_image
    if bg is None or not bg.stretched or bg.data is None:
        return None
    try:
        img = Image.open(io.BytesIO(bg.data)).convert("RGB")
    except OSError:
        return None
    if img.size != tuple(size):
        img = img.resize(tuple(size), Image.Resampling.LANCZOS)
    return np.asarray(img)


def _check_movie_frame(s: SlideInfo, analysis: Analysis, original: np.ndarray | None, size) -> None:
    if s.movie_frame is None or original is None:
        return
    mid, index = s.movie_frame
    path = analysis.movies[mid].frames[index]
    frame = Image.open(path).convert("RGB")
    if frame.size != tuple(size):
        frame = frame.resize(tuple(size), Image.Resampling.LANCZOS)
    if np.abs(np.asarray(frame).astype(np.int16) - original).max() > 2:
        s.warnings.append(f"background {s.background_image.name!r} differs from {path}: "
                          "was the frame re-rendered after being put in the slide?")


def _profiles_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "crappy" / "lo-profiles"


def _save_png(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array).save(path, compress_level=3)


class _Renderer:
    """Writes document variants, exports them, and gives access to the rendered pages."""

    def __init__(self, pkg: OdfPackage, slides: list[SlideInfo], work: Path, size, workers, log):
        self.pkg, self.slides, self.work, self.size, self.workers, self.log = pkg, slides, work, size, workers, log
        self.jobs: dict[str, ExportJob] = {}
        self.rasters: dict[str, PdfRaster] = {}

    def add(self, name: str, variant: OdfPackage, pages: list[int] | None) -> None:
        path = self.work / f"{name}.odp"
        variant.save(path)
        self.jobs[name] = ExportJob(path, pages)

    def add_steps(self, prefix: str, classes: dict[int, str]) -> None:
        """Variants 'prefix_step{k}_{i}' for the slides in `classes` (number -> background class)."""
        max_steps = max(self.slides[n - 1].animation.n_steps for n in classes)
        for k in range(max_steps):
            numbers = [n for n in classes if self.slides[n - 1].animation.n_steps > k]
            for i in (0, 1):
                v = self.pkg.copy()
                set_page_backdrops(v, {n - 1: BACKDROPS[classes[n]][i] for n in numbers})
                hider = StepHider(v)
                pages = v.pages()
                for n in numbers:
                    before = len(hider.warnings)
                    hider.apply(pages[n - 1], self.slides[n - 1].animation, k)
                    for w in hider.warnings[before:]:
                        if w not in self.slides[n - 1].warnings:
                            self.slides[n - 1].warnings.append(w)
                full = len(numbers) == len(self.slides)
                self.add(f"{prefix}_step{k}_{i}", v, None if full else numbers)

    def run(self) -> None:
        pending = [name for name in self.jobs if name not in self.rasters]
        done = [0]

        def progress(job: ExportJob) -> None:
            done[0] += 1
            self.log(f"  exported {done[0]}/{len(pending)}  {job.odp.stem}")

        export_pdfs([self.jobs[n] for n in pending], _profiles_dir(), self.workers, progress)
        for name in pending:
            self.rasters[name] = PdfRaster(self.jobs[name].pdf, self.size)

    def page(self, name: str, number: int) -> np.ndarray:
        pages = self.jobs[name].pages
        return self.rasters[name][number - 1 if pages is None else pages.index(number)]

    def close(self) -> None:
        for r in self.rasters.values():
            r.close()


def _rebuild(r: _Renderer, prefix: str, s: SlideInfo, cls: str, background, reference) -> Rebuilt:
    b1, b2 = (hex_to_rgb(c) for c in BACKDROPS[cls])
    overlays = [unmatte(r.page(f"{prefix}_step{k}_0", s.number), r.page(f"{prefix}_step{k}_1", s.number), b1, b2)
                for k in range(s.animation.n_steps)]
    mismatch = None
    if not s.animation.has_exit:
        # the last step shows every object, as LibreOffice's own export does
        diff = np.abs(over(overlays[-1], background).astype(np.int16) - reference).max(-1)
        mismatch = float((diff > CHECK_TOLERANCE).mean())
    return Rebuilt(cls, overlays, mismatch)


def build(odp: Path, out_dir: Path | None = None, size: tuple[int, int] = (1920, 1080),
          workers: int | None = None, force: bool = False, keep_work: bool = False,
          log=print) -> dict:
    odp = Path(odp).resolve()
    out_dir = Path(out_dir or default_output_dir(odp)).resolve()
    cfg = load_config(config_path_for(odp))
    key = _source_key(odp, cfg, size)

    manifest_path = out_dir / MANIFEST
    if not force and manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old.get("source_key") == key:
            log(f"{odp.name}: up to date ({manifest_path})")
            return old

    t0 = time.monotonic()
    pkg = OdfPackage.load(odp)
    analysis = analyse(pkg, cfg)
    slides, warnings = analysis.slides, analysis.warnings
    pages = pkg.pages()
    classes = {s.number: background_class(pkg, pages[s.number - 1]) for s in slides}

    work = out_dir / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    r = _Renderer(pkg, slides, work, size, workers, log)

    r.add("reference", pkg.copy(), None)
    bg = pkg.copy()
    strip_to_background(bg)
    r.add("background", bg, None)
    r.add_steps("main", classes)
    log(f"{odp.name}: {len(slides)} slides, up to {max(s.animation.n_steps for s in slides)} click steps, "
        f"{len(r.jobs)} LibreOffice exports")

    slide_entries = []
    encoder = ThreadPoolExecutor(1)        # movies encode while LibreOffice renders
    movies_job = encoder.submit(_encode_movies, analysis, out_dir / "movies", size, log)
    try:
        r.run()
        movies = movies_job.result()
        backgrounds = {s.number: r.page("background", s.number) for s in slides}
        references = {s.number: r.page("reference", s.number) for s in slides}
        results = {s.number: _rebuild(r, "main", s, classes[s.number], backgrounds[s.number], references[s.number])
                   for s in slides}

        retry = {n: other_class(res.background_class) for n, res in results.items()
                 if res.mismatch is not None and res.mismatch > CHECK_MAX_FRACTION}
        if retry:
            log(f"  slide(s) {sorted(retry)} do not match LibreOffice's render: retrying with the other backdrops")
            r.add_steps("retry", retry)
            r.run()
            for n, cls in retry.items():
                s = slides[n - 1]
                other = _rebuild(r, "retry", s, cls, backgrounds[n], references[n])
                if other.mismatch < results[n].mismatch:
                    results[n] = other

        for s in slides:
            res = results[s.number]
            if res.mismatch is not None and res.mismatch > CHECK_MAX_FRACTION:
                s.warnings.append(f"rebuilt slide differs from LibreOffice's render on {res.mismatch:.2%} of pixels")
            rel = Path("slides") / f"{s.number:03d}"
            original = _original_background(s, size)
            _check_movie_frame(s, analysis, original, size)
            _save_png(out_dir / rel / "background.png", backgrounds[s.number] if original is None else original)
            steps = []
            for k, overlay in enumerate(res.overlays):
                _save_png(out_dir / rel / f"step{k}.png", overlay)
                eff = s.animation.step_effect(k)
                steps.append({"overlay": str(rel / f"step{k}.png"),
                              "effect": {"kind": eff.kind, "duration": eff.duration}})

            transition = s.transition.to_json()
            if s.clip is not None:
                c = s.clip
                end = c.end if c.end >= 0 else movies[c.movie]["count"] - 1
                transition = {"kind": "clip", "movie": c.movie, "start": c.start, "end": end, "fps": c.fps,
                              "duration": abs(end - c.start) / c.fps, "overlay_in": c.overlay_in,
                              "overlay_out": c.overlay_out, "source": c.source}
            slide_entries.append({
                "number": s.number, "name": s.name, "hidden": s.hidden, "notes": s.notes,
                "background": str(rel / "background.png"), "steps": steps,
                "transition": transition, "background_class": res.background_class,
                "check_mismatch": res.mismatch, "warnings": s.warnings,
            })
            check = "" if res.mismatch is None else f"  check {res.mismatch:.3%}"
            log(f"  slide {s.number:3d} {s.name[:40]!r:44} {len(steps)} step(s)  {transition['kind']}{check}")
    finally:
        r.close()
        encoder.shutdown(wait=True)

    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    manifest = {
        "format": FORMAT_VERSION, "crappy": __version__, "source": str(odp), "source_key": key,
        "config": str(cfg.path) if cfg.path else None,
        "size": list(size), "slides": slide_entries, "movies": movies, "warnings": warnings,
        "build_seconds": round(time.monotonic() - t0, 1),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    for s in slide_entries:
        for w in s["warnings"]:
            log(f"warning: slide {s['number']} ({s['name']}): {w}")
    for w in warnings:
        log(f"warning: {w}")
    log(f"done in {manifest['build_seconds']} s -> {out_dir}")
    return manifest
