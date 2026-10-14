"""Command line: crappy info | build | preview | play."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from crappy.build import analyse, build, default_output_dir
from crappy.config import ConfigError, config_path_for, load_config
from crappy.odf import OdfPackage
from crappy.movie import EncodeError
from crappy.render import RenderError


def _size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT, e.g. 1920x1080") from None


def cmd_info(args) -> int:
    odp = Path(args.odp)
    analysis = analyse(OdfPackage.load(odp), load_config(config_path_for(odp)))
    slides, warnings = analysis.slides, analysis.warnings
    for s in slides:
        if s.clip:
            c = s.clip
            t = (f"clip {c.movie} frames {c.start}->{c.end} ({c.duration:g}s)" if c.end >= 0 else f"clip {c.movie}") \
                + " fade out " + (f"{c.overlay_out:g}s" if c.overlay_out >= 0 else f"{-c.overlay_out:g}s before") \
                + " / in " + (f"{c.overlay_in:g}s" if c.overlay_in >= 0 else f"{-c.overlay_in:g}s after")
        else:
            t = s.transition.kind + (f" {s.transition.duration:g}s" if s.transition.kind != "cut" else "")
        bg = f"  bg={s.background_image.name}" if s.background_image else ""
        print(f"{s.number:3d}  {s.name[:40]:40}  steps={s.animation.n_steps}  in={t}{bg}"
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


def cmd_play(args) -> int:
    from crappy.player.app import run, screens_summary
    if args.list_screens:
        print("\n".join(screens_summary()))
        return 0
    if args.talk is None:
        print("error: give a .odp or a manifest.json", file=sys.stderr)
        return 2
    talk = Path(args.talk)
    if talk.suffix == ".odp":
        out = Path(args.output or default_output_dir(talk.resolve()))
        build(talk, out, args.size, args.jobs)
        manifest = out / "manifest.json"
    elif talk.is_dir():
        manifest = talk / "manifest.json"
    else:
        manifest = talk
    return run(manifest, args.screen, args.windowed, args.start, args.software,
               args.presenter, args.presenter_screen)


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

    p = sub.add_parser("play", help="show the talk (builds it first when given the .odp)")
    p.add_argument("talk", nargs="?", help="talk.odp, its .crappy folder, or a manifest.json")
    p.add_argument("-s", "--screen", type=int, help="screen number (see --list-screens); "
                   "default: a non-primary screen if there is one")
    p.add_argument("--list-screens", action="store_true", help="list screens and exit")
    p.add_argument("-w", "--windowed", action="store_true", help="in a window instead of fullscreen")
    p.add_argument("--start", type=int, help="start at this slide number")
    p.add_argument("--software", action="store_true", help="draw without OpenGL")
    p.add_argument("--presenter", choices=("auto", "on", "off"), default="auto",
                   help="presenter view (notes, next slide, timer): auto = when there is a second screen; "
                        "'on' with a single screen opens it in a window (rehearsal)")
    p.add_argument("--presenter-screen", type=int, help="screen of the presenter view (see --list-screens)")
    p.add_argument("-o", "--output", type=Path, help="build folder (default: <talk>.crappy next to the .odp)")
    p.add_argument("--size", type=_size, default=(1920, 1080), help="build size WIDTHxHEIGHT (default 1920x1080)")
    p.add_argument("-j", "--jobs", type=int, help="parallel LibreOffice instances for the build")
    p.set_defaults(func=cmd_play)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, RenderError, EncodeError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
