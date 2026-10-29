# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""`crappy build`: an .odp -> per-slide background + transparent content layers + effect timing.

Render passes (each one a whole-document LibreOffice PDF export, run in parallel):
  reference        the untouched talk: self-check of every rebuilt slide
  background       objects removed: what Impress draws as background
  base / pair i    every slide reduced to its base layer (crappy.layers), over
                   backdrop i of its pair (crappy.background.BACKDROPS)
  extra / pair i   one extra slide per other layer (animated objects, static
                   slices between them), over the same backdrops
Each layer comes out of the two backdrop renders by difference matting; the
player shows, fades and moves the animated ones following the effects' timing.

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
from crappy.layers import SlidePlan, make_base, make_extra, page_size_cm, plan_slide
from crappy.motion import PathError, flatten, resample
from crappy.variants import set_page_backdrops, strip_to_background

MANIFEST = "manifest.json"
FORMAT_VERSION = 2
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
        """Whole transition: the movie, plus fades placed before/after it (negative values)."""
        return abs(self.end - self.start) / self.fps + max(0.0, -self.overlay_out) + max(0.0, -self.overlay_in)


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
        if key in by_key and o.replaces_transition:
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

    # fade times given for a single transition
    for key, o in cfg.overrides.items():
        if key in by_key and not o.replaces_transition:
            s = by_key[key]
            if s.clip is None:
                warnings.append(f"config: [transition.{key!r}] sets fade times but slide {s.number} "
                                "is not entered through a clip")
                continue
            if o.overlay_in is not None:
                s.clip.overlay_in = float(o.overlay_in)
            if o.overlay_out is not None:
                s.clip.overlay_out = float(o.overlay_out)
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

    def add_layers(self, prefix: str, plans: dict[int, SlidePlan], classes: dict[int, str]) -> dict:
        """Exports '{prefix}_base_{i}' and '{prefix}_extra_{i}' (i: backdrop of the pair) for the
        slides in `classes` (number -> background class). Returns {(number, layer index): extra page}."""
        numbers = sorted(classes)
        n_pages = len(self.slides)
        base = make_base(self.pkg, {n: plans[n] for n in numbers})
        extra_pkg, extra = make_extra(self.pkg, {n: plans[n] for n in numbers if plans[n].animated})
        extra_pages = {key: n_pages + 1 + j for j, key in enumerate(extra)}
        for i in (0, 1):
            b = base.copy()
            set_page_backdrops(b, {n - 1: BACKDROPS[classes[n]][i] for n in numbers})
            self.add(f"{prefix}_base_{i}", b, None if len(numbers) == n_pages else numbers)
            if extra:
                e = extra_pkg.copy()
                set_page_backdrops(e, {page - 1: BACKDROPS[classes[n]][i] for (n, _), page in extra_pages.items()})
                self.add(f"{prefix}_extra_{i}", e, list(extra_pages.values()))
        return extra_pages

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


@dataclass
class Rebuilt:
    background_class: str
    layers: list[np.ndarray]          # full-size RGBA, in stacking order (same order as plan.layers)
    mismatch: float


def _rebuild(r: _Renderer, prefix: str, s: SlideInfo, plan: SlidePlan, extra_pages: dict, cls: str,
             background, reference) -> Rebuilt:
    b1, b2 = (hex_to_rgb(c) for c in BACKDROPS[cls])

    def matte(name: str, page: int) -> np.ndarray:
        return unmatte(r.page(f"{name}_0", page), r.page(f"{name}_1", page), b1, b2)

    layers = [matte(f"{prefix}_base", s.number)]
    for index in range(1, len(plan.layers)):
        layers.append(matte(f"{prefix}_extra", extra_pages[(s.number, index)]))
    # every layer at its place, everything visible: what LibreOffice's own export shows
    composite = background
    for layer in layers:
        composite = over(layer, composite)
    diff = np.abs(composite.astype(np.int16) - reference).max(-1)
    return Rebuilt(cls, layers, float((diff > CHECK_TOLERANCE).mean()))


def _crop(layer: np.ndarray) -> tuple[np.ndarray, int, int] | None:
    alpha = layer[..., 3]
    rows, cols = np.flatnonzero(alpha.any(1)), np.flatnonzero(alpha.any(0))
    if rows.size == 0:
        return None
    y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    return layer[y0:y1, x0:x1], int(x0), int(y0)


def _steps_json(s: SlideInfo, plan: SlidePlan, page_px: tuple[float, float]) -> list[dict]:
    """Click steps with their timed effects. Effects before the first click become an
    automatic step after an initial one (state before they play)."""
    uid = {(u.target, u.sub_item): u.uid for u in plan.units}

    def events(group) -> list[dict]:
        out = []
        for e in sorted(group, key=lambda e: e.start):
            if e.unit not in uid:
                continue
            ev = {"unit": uid[e.unit], "kind": e.kind, "start": round(e.start, 4), "duration": round(e.duration, 4)}
            if e.kind == "motion":
                try:
                    points = resample(flatten(e.path), page_px)
                except PathError as err:
                    s.warnings.append(f"motion path ignored: {err}")
                    continue
                ev |= {"points": [[round(x, 2), round(y, 2)] for x, y in points],
                       "accelerate": e.accelerate, "decelerate": e.decelerate}
            out.append(ev)
        return out

    def step(group, auto=False) -> dict:
        evs = events(group)
        return {"auto": auto, "duration": round(max((e["start"] + e["duration"] for e in evs), default=0.0), 4),
                "events": evs}

    groups = s.animation.groups
    steps = [step([])]
    if s.animation.auto_start:
        steps.append(step(groups[0], auto=True))
    return steps + [step(g) for g in groups[1:]]


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

    plans = {s.number: plan_slide(pages[s.number - 1], s.animation, s.number) for s in slides}
    for s in slides:
        s.warnings += plans[s.number].warnings
    w_cm, h_cm = page_size_cm(pkg)
    scale = min(size[0] / w_cm, size[1] / h_cm)
    page_px = (w_cm * scale, h_cm * scale)

    r.add("reference", pkg.copy(), None)
    bg = pkg.copy()
    strip_to_background(bg)
    r.add("background", bg, None)
    extra_pages = r.add_layers("main", plans, classes)
    log(f"{odp.name}: {len(slides)} slides, {sum(len(p.units) for p in plans.values())} animated objects, "
        f"{len(r.jobs)} LibreOffice exports")

    slide_entries = []
    encoder = ThreadPoolExecutor(1)        # movies encode while LibreOffice renders
    movies_job = encoder.submit(_encode_movies, analysis, out_dir / "movies", size, log)
    try:
        r.run()
        movies = movies_job.result()
        backgrounds = {s.number: r.page("background", s.number) for s in slides}
        references = {s.number: r.page("reference", s.number) for s in slides}
        results = {s.number: _rebuild(r, "main", s, plans[s.number], extra_pages, classes[s.number],
                                      backgrounds[s.number], references[s.number]) for s in slides}

        retry = {n: other_class(res.background_class) for n, res in results.items()
                 if res.mismatch > CHECK_MAX_FRACTION}
        if retry:
            log(f"  slide(s) {sorted(retry)} do not match LibreOffice's render: retrying with the other backdrops")
            retry_pages = r.add_layers("retry", plans, retry)
            r.run()
            for n, cls in retry.items():
                other = _rebuild(r, "retry", slides[n - 1], plans[n], retry_pages, cls, backgrounds[n], references[n])
                if other.mismatch < results[n].mismatch:
                    results[n] = other

        for s in slides:
            res, plan = results[s.number], plans[s.number]
            if res.mismatch > CHECK_MAX_FRACTION:
                s.warnings.append(f"rebuilt slide differs from LibreOffice's render on {res.mismatch:.2%} of pixels")
            rel = Path("slides") / f"{s.number:03d}"
            original = _original_background(s, size)
            _check_movie_frame(s, analysis, original, size)
            _save_png(out_dir / rel / "background.png", backgrounds[s.number] if original is None else original)
            layers = []
            for index, (layer, rgba) in enumerate(zip(plan.layers, res.layers)):
                cropped = _crop(rgba)
                if cropped is None:
                    continue
                pixels, x, y = cropped
                _save_png(out_dir / rel / f"layer{index:03d}.png", pixels)
                layers.append({"file": str(rel / f"layer{index:03d}.png"), "x": x, "y": y, "unit": layer.unit})
            steps = _steps_json(s, plan, page_px)
            units = {u.uid: {"visible": s.animation.initially_visible((u.target, u.sub_item))} for u in plan.units}

            transition = s.transition.to_json()
            if s.clip is not None:
                c = s.clip
                end = c.end if c.end >= 0 else movies[c.movie]["count"] - 1
                transition = {"kind": "clip", "movie": c.movie, "start": c.start, "end": end, "fps": c.fps,
                              "duration": abs(end - c.start) / c.fps + max(0.0, -c.overlay_out)
                              + max(0.0, -c.overlay_in), "overlay_in": c.overlay_in,
                              "overlay_out": c.overlay_out, "source": c.source}
            slide_entries.append({
                "number": s.number, "name": s.name, "hidden": s.hidden, "notes": s.notes,
                "background": str(rel / "background.png"), "layers": layers, "units": units, "steps": steps,
                "transition": transition, "background_class": res.background_class,
                "check_mismatch": res.mismatch, "warnings": s.warnings,
            })
            log(f"  slide {s.number:3d} {s.name[:40]!r:44} {len(steps)} step(s) {len(units):3d} animated  "
                f"{transition['kind']}  check {res.mismatch:.3%}")
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
