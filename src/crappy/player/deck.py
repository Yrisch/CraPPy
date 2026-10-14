"""A built talk (manifest.json) as seen by the player."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# A clip whose movie is missing from the build shows as a fade of this length at most.
CLIP_FALLBACK_MAX = 1.0


@dataclass(frozen=True)
class ClipRef:
    """Movie frames start -> end (backwards when end < start) played between two slides."""
    movie: str
    start: int
    end: int
    fps: float
    overlay_in: float
    overlay_out: float

    @property
    def n_frames(self) -> int:
        return abs(self.end - self.start) + 1

    def index(self, progress: float) -> int:
        """Clip frame index (0 .. n_frames - 1) shown at a progress in [0, 1]."""
        return round(progress * (self.n_frames - 1))

    def frame(self, index: int) -> int:
        """Movie frame number of a clip frame index."""
        return self.start + index * (1 if self.end >= self.start else -1)

    def overlay_alphas(self, progress: float) -> tuple[float, float]:
        """Opacity of the outgoing and of the incoming slide content."""
        duration = (self.n_frames - 1) / self.fps
        t = progress * duration
        out = 1.0 - min(1.0, t / self.overlay_out) if self.overlay_out > 0 else float(t <= 0)
        start_in = duration - self.overlay_in
        inc = min(1.0, max(0.0, (t - start_in) / self.overlay_in)) if self.overlay_in > 0 else float(t >= duration)
        return out, inc


@dataclass(frozen=True)
class Effect:
    """How the picture changes between two positions.

    kind: cut | fade | fade_color | push | cover | uncover | wipe | clip
    """
    kind: str = "cut"
    duration: float = 0.0
    side: str | None = None
    color: str | None = None
    clip: ClipRef | None = None

    @property
    def instant(self) -> bool:
        return self.kind == "cut" or self.duration <= 0


@dataclass
class DeckSlide:
    number: int                      # Impress slide number (1-based)
    name: str
    hidden: bool
    notes: str
    background: Path
    overlays: list[Path]
    step_effects: list[Effect]       # step_effects[k]: entering step k (k = 0 unused)
    transition: Effect               # entering this slide
    raw_transition: dict = field(default_factory=dict)

    @property
    def n_steps(self) -> int:
        return len(self.overlays)


@dataclass(frozen=True)
class MovieInfo:
    video: Path
    first: int          # movie frame number of the video's first frame
    count: int


@dataclass
class Deck:
    root: Path
    size: tuple[int, int]
    slides: list[DeckSlide]
    movies: dict[str, MovieInfo] = field(default_factory=dict)

    @classmethod
    def load(cls, manifest_path: Path) -> Deck:
        manifest_path = Path(manifest_path)
        data = json.loads(manifest_path.read_text())
        root = manifest_path.parent
        movies = {mid: MovieInfo(root / m["video"], m["first"], m["count"])
                  for mid, m in data.get("movies", {}).items()}
        slides = []
        for s in data["slides"]:
            t = s["transition"]
            if t["kind"] == "clip" and t.get("movie") in movies and (root / movies[t["movie"]].video).exists():
                clip = ClipRef(t["movie"], t["start"], t["end"], t["fps"], t["overlay_in"], t["overlay_out"])
                transition = Effect("clip", t["duration"], clip=clip)
            elif t["kind"] == "clip":
                transition = Effect("fade", min(t.get("duration", CLIP_FALLBACK_MAX), CLIP_FALLBACK_MAX))
            else:
                transition = Effect(t["kind"], t.get("duration", 0.0), t.get("side"), t.get("color"))
            slides.append(DeckSlide(
                number=s["number"], name=s["name"], hidden=s["hidden"], notes=s.get("notes", ""),
                background=root / s["background"],
                overlays=[root / st["overlay"] for st in s["steps"]],
                step_effects=[Effect(st["effect"]["kind"], st["effect"]["duration"]) for st in s["steps"]],
                transition=transition, raw_transition=t,
            ))
        return cls(root, tuple(data["size"]), slides, movies)

    def index_of_number(self, number: int) -> int | None:
        for i, s in enumerate(self.slides):
            if s.number == number:
                return i
        return None
