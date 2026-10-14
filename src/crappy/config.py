"""Side file `<talk>.crappy.toml`, next to `<talk>.odp`.

    [defaults]
    overlay_out = 0.3          # s, outgoing slide content fades at clip start
    overlay_in  = 0.5          # s, incoming slide content fades in at clip end

    # transition INTO the slide named "halo_zoom" (rename slides in Impress'
    # slide pane; a slide number like "11" works too)
    [transition.halo_zoom]
    frames = "renders/zoom_halo/*.png"     # PNG sequence, relative to this file
    fps = 30
    overlay_in = 1.0                       # per-transition override

    # override a LibreOffice transition without a clip
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

    @property
    def duration(self) -> float:
        return len(self.frames) / self.fps if self.frames else 0.0

    def to_json(self, root: Path) -> dict:
        def rel(p: Path) -> str:
            try:
                return str(p.relative_to(root))
            except ValueError:
                return str(p)
        d = {"fps": self.fps, "overlay_in": self.overlay_in, "overlay_out": self.overlay_out}
        if self.frames:
            d["frames"] = [rel(p) for p in self.frames]
        if self.clip:
            d["clip"] = rel(self.clip)
        return d


@dataclass
class TransitionOverride:
    kind: str | None = None
    duration: float | None = None
    side: str | None = None
    color: str | None = None


@dataclass
class Config:
    path: Path | None = None
    overlay_in: float = 0.5
    overlay_out: float = 0.3
    clips: dict[str, ClipSpec] = field(default_factory=dict)
    overrides: dict[str, TransitionOverride] = field(default_factory=dict)


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def config_path_for(odp: Path) -> Path:
    return odp.with_name(odp.stem + ".crappy.toml")


def load_config(path: Path | None) -> Config:
    if path is None or not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: {e}") from None
    unknown = set(data) - {"defaults", "transition"}
    if unknown:
        raise ConfigError(f"{path.name}: unknown section(s) {sorted(unknown)}")
    defaults = data.get("defaults", {})
    cfg = Config(path=path,
                 overlay_in=float(defaults.get("overlay_in", 0.5)),
                 overlay_out=float(defaults.get("overlay_out", 0.3)))
    base = path.parent
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
                pattern = str(base / spec["frames"])
                clip.frames = [Path(p) for p in sorted(glob.glob(pattern), key=natural_key)]
                if not clip.frames:
                    raise ConfigError(f"{where}: no file matches {spec['frames']!r}")
            if "clip" in spec:
                clip.clip = base / spec["clip"]
                if not clip.clip.exists():
                    raise ConfigError(f"{where}: {spec['clip']!r} does not exist")
            cfg.clips[slide] = clip
        else:
            o = TransitionOverride(kind=spec.get("kind"), duration=spec.get("duration"),
                                   side=spec.get("side"), color=spec.get("color"))
            if o.kind is not None and o.kind not in _KINDS:
                raise ConfigError(f"{where}: kind must be one of {sorted(_KINDS)}")
            if o.side is not None and o.side not in _SIDES:
                raise ConfigError(f"{where}: side must be one of {sorted(_SIDES)}")
            cfg.overrides[slide] = o
    return cfg
