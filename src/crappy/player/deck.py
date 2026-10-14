"""A built talk (manifest.json) as seen by the player."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Clips are played from phase 3 on; until then they show as a fade of this length at most.
CLIP_FALLBACK_MAX = 1.0


@dataclass(frozen=True)
class Effect:
    """How the picture changes between two positions.

    kind: cut | fade | fade_color | push | cover | uncover | wipe
    """
    kind: str = "cut"
    duration: float = 0.0
    side: str | None = None
    color: str | None = None

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


@dataclass
class Deck:
    root: Path
    size: tuple[int, int]
    slides: list[DeckSlide]

    @classmethod
    def load(cls, manifest_path: Path) -> Deck:
        manifest_path = Path(manifest_path)
        data = json.loads(manifest_path.read_text())
        root = manifest_path.parent
        slides = []
        for s in data["slides"]:
            t = s["transition"]
            if t["kind"] == "clip":
                frames = len(t.get("frames", []))
                duration = frames / t.get("fps", 30) if frames else CLIP_FALLBACK_MAX
                transition = Effect("fade", min(duration, CLIP_FALLBACK_MAX))
            else:
                transition = Effect(t["kind"], t.get("duration", 0.0), t.get("side"), t.get("color"))
            slides.append(DeckSlide(
                number=s["number"], name=s["name"], hidden=s["hidden"], notes=s.get("notes", ""),
                background=root / s["background"],
                overlays=[root / st["overlay"] for st in s["steps"]],
                step_effects=[Effect(st["effect"]["kind"], st["effect"]["duration"]) for st in s["steps"]],
                transition=transition, raw_transition=t,
            ))
        return cls(root, tuple(data["size"]), slides)

    def index_of_number(self, number: int) -> int | None:
        for i, s in enumerate(self.slides):
            if s.number == number:
                return i
        return None
