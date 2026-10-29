# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""Side file `<talk>.crappy.toml`, next to `<talk>.odp`.

    [defaults]
    overlay_out = 0.3          # s, outgoing slide content fades at clip start
    overlay_in  = 0.5          # s, incoming slide content fades in at clip end

    # A rendered frame sequence. A slide whose background image is one of these
    # frames (same file name, e.g. frame_00030) is tied to that frame; between
    # two such slides the transition plays the movie from one frame to the other.
    [movie]
    frames = "../Movie_background/frame_*.png"   # relative to this file
    fps = 30
    # several sequences: [[movie]] tables instead of [movie]

    # explicit clip INTO the slide named "halo_zoom" (rename slides in Impress'
    # slide pane; a slide number like "11" works too)
    [transition.halo_zoom]
    frames = "renders/zoom_halo/*.png"     # or: clip = "renders/zoom.mp4"
    fps = 30
    overlay_in = 1.0                       # per-transition override

    # only the content fades of the clip deduced from the movie; a negative
    # value fades outside the movie (-0.5: fade in during 0.5 s once it ended)
    [transition.page3]
    overlay_out = 0.8
    overlay_in = -0.5

    # override a transition (also one deduced from a movie)
    [transition."Conclusion and Perspectives"]
    kind = "fade_color"
    color = "#000000"
    duration = 1.5
"""

from __future__ import annotations

import glob
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_CLIP_KEYS = {"frames", "clip", "fps", "overlay_in", "overlay_out"}
_PLAIN_KEYS = {"kind", "duration", "side", "color"}
_MOVIE_KEYS = {"frames", "fps", "overlay_in", "overlay_out"}
_KINDS = {"cut", "fade", "fade_color", "push", "cover", "uncover", "wipe"}
_SIDES = {"left", "right", "top", "bottom"}


class ConfigError(ValueError):
    pass


@dataclass
class ClipSpec:
    frames: list[Path] = field(default_factory=list)   # PNG sequence (natural order)
    clip: Path | None = None                           # or an existing video file
    fps: float = 30.0
    overlay_in: float = 0.5
    overlay_out: float = 0.3


@dataclass
class MovieSpec:
    frames: list[Path]
    fps: float = 30.0
    overlay_in: float = 0.5
    overlay_out: float = 0.3

    def index_of_stem(self) -> dict[str, int]:
        return {p.stem: i for i, p in enumerate(self.frames)}


@dataclass
class TransitionOverride:
    kind: str | None = None
    duration: float | None = None
    side: str | None = None
    color: str | None = None
    overlay_in: float | None = None      # only fade times: tunes the clip deduced from the movie
    overlay_out: float | None = None

    @property
    def replaces_transition(self) -> bool:
        return any(v is not None for v in (self.kind, self.duration, self.side, self.color))


@dataclass
class Config:
    path: Path | None = None
    overlay_in: float = 0.5
    overlay_out: float = 0.3
    movies: list[MovieSpec] = field(default_factory=list)
    clips: dict[str, ClipSpec] = field(default_factory=dict)
    overrides: dict[str, TransitionOverride] = field(default_factory=dict)

    def media_files(self) -> list[Path]:
        """Every file the build reads from the side file (for change detection)."""
        files = [p for m in self.movies for p in m.frames]
        for c in self.clips.values():
            files += c.frames + ([c.clip] if c.clip else [])
        return files


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def config_path_for(odp: Path) -> Path:
    return odp.with_name(odp.stem + ".crappy.toml")


def _frames(base: Path, pattern: str, where: str) -> list[Path]:
    files = [Path(p) for p in sorted(glob.glob(str(base / pattern)), key=natural_key)]
    if not files:
        raise ConfigError(f"{where}: no file matches {pattern!r}")
    return files


def load_config(path: Path | None) -> Config:
    if path is None or not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: {e}") from None
    unknown = set(data) - {"defaults", "transition", "movie"}
    if unknown:
        raise ConfigError(f"{path.name}: unknown section(s) {sorted(unknown)}")
    defaults = data.get("defaults", {})
    cfg = Config(path=path,
                 overlay_in=float(defaults.get("overlay_in", 0.5)),
                 overlay_out=float(defaults.get("overlay_out", 0.3)))
    base = path.parent

    movies = data.get("movie", [])
    for i, spec in enumerate([movies] if isinstance(movies, dict) else movies):
        where = f"{path.name} [movie]" + (f" #{i + 1}" if not isinstance(movies, dict) else "")
        if set(spec) - _MOVIE_KEYS:
            raise ConfigError(f"{where}: unknown key(s) {sorted(set(spec) - _MOVIE_KEYS)}")
        if "frames" not in spec:
            raise ConfigError(f"{where}: 'frames' is required")
        cfg.movies.append(MovieSpec(frames=_frames(base, spec["frames"], where),
                                    fps=float(spec.get("fps", 30)),
                                    overlay_in=float(spec.get("overlay_in", cfg.overlay_in)),
                                    overlay_out=float(spec.get("overlay_out", cfg.overlay_out))))

    for slide, spec in data.get("transition", {}).items():
        where = f"{path.name} [transition.{slide!r}]"
        keys = set(spec)
        if keys - _CLIP_KEYS - _PLAIN_KEYS:
            raise ConfigError(f"{where}: unknown key(s) {sorted(keys - _CLIP_KEYS - _PLAIN_KEYS)}")
        if "frames" in spec or "clip" in spec:
            if keys & _PLAIN_KEYS:
                raise ConfigError(f"{where}: {sorted(keys & _PLAIN_KEYS)} cannot be combined with a clip")
            clip = ClipSpec(fps=float(spec.get("fps", 30)),
                            overlay_in=float(spec.get("overlay_in", cfg.overlay_in)),
                            overlay_out=float(spec.get("overlay_out", cfg.overlay_out)))
            if "frames" in spec:
                clip.frames = _frames(base, spec["frames"], where)
            if "clip" in spec:
                clip.clip = base / spec["clip"]
                if not clip.clip.exists():
                    raise ConfigError(f"{where}: {spec['clip']!r} does not exist")
            cfg.clips[slide] = clip
        else:
            if keys & {"fps"}:
                raise ConfigError(f"{where}: 'fps' needs 'frames' or 'clip'")
            o = TransitionOverride(kind=spec.get("kind"), duration=spec.get("duration"),
                                   side=spec.get("side"), color=spec.get("color"),
                                   overlay_in=spec.get("overlay_in"), overlay_out=spec.get("overlay_out"))
            if o.replaces_transition and (o.overlay_in is not None or o.overlay_out is not None):
                raise ConfigError(f"{where}: overlay_in/overlay_out only apply to clips, not to kind = ...")
            if o.kind is not None and o.kind not in _KINDS:
                raise ConfigError(f"{where}: kind must be one of {sorted(_KINDS)}")
            if o.side is not None and o.side not in _SIDES:
                raise ConfigError(f"{where}: side must be one of {sorted(_SIDES)}")
            cfg.overrides[slide] = o
    return cfg
