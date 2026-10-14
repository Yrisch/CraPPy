"""Command line: crappy info | build | preview."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from crappy.build import analyse, build, default_output_dir
from crappy.config import ConfigError, config_path_for, load_config
from crappy.odf import OdfPackage
from crappy.render import RenderError


def _size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT, e.g. 1920x1080") from None


def cmd_info(args) -> int:
    odp = Path(args.odp)
    slides, warnings = analyse(OdfPackage.load(odp), load_config(config_path_for(odp)))
    for s in slides:
        t = "clip" if s.clip else s.transition.kind
        extra = f" {s.transition.duration:g}s" if not s.clip and t != "cut" else ""
        print(f"{s.number:3d}  {s.name[:45]:45}  steps={s.animation.n_steps}  in={t}{extra}"
              + ("  [hidden]" if s.hidden else ""))
        for w in s.warnings:
            print(f"       warning: {w}")
    for w in warnings:
        print(f"warning: {w}")
    return 0


def cmd_build(args) -> int:
    build(Path(args.odp), args.output, args.size, args.jobs, args.force, args.keep_work)
    return 0


def cmd_preview(args) -> int:
    from crappy.preview import write_previews
    odp = Path(args.odp)
    out = Path(args.output or default_output_dir(odp.resolve()))
    manifest = build(odp, out, args.size, args.jobs, args.force)
    print(f"contact sheet: {write_previews(manifest, out.resolve())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crappy", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("info", help="list slides, click steps and transitions (no rendering)")
    p.add_argument("odp")
    p.set_defaults(func=cmd_info)

    for name, func, text in (("build", cmd_build, "render backgrounds and overlays"),
                             ("preview", cmd_preview, "build, then write composited PNGs and a contact sheet")):
        p = sub.add_parser(name, help=text)
        p.add_argument("odp")
        p.add_argument("-o", "--output", type=Path, help="output folder (default: <talk>.crappy next to the .odp)")
        p.add_argument("--size", type=_size, default=(1920, 1080), help="WIDTHxHEIGHT (default 1920x1080)")
        p.add_argument("-j", "--jobs", type=int, help="parallel LibreOffice instances (default: half the CPUs, at most 8)")
        p.add_argument("-f", "--force", action="store_true", help="rebuild even if up to date")
        if name == "build":
            p.add_argument("--keep-work", action="store_true", help="keep intermediate .odp/.pdf files")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, RenderError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
