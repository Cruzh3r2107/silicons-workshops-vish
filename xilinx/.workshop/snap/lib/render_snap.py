#!/usr/bin/env python3
"""Render the kernel-snap Snapcraft project from project.yaml and the kernel metadata."""
import argparse
import json
import re
import string
import sys
from pathlib import Path

SNAP_NAME_RE = re.compile(r"^[a-z0-9](?:-?[a-z0-9])*$")

KERNEL_YAML = """\
assets:
  dtbs:
    update: true
    content:
      - dtbs/
"""


class RenderError(Exception):
    pass


class _Template(string.Template):
    delimiter = "@"


def _load_cfg(project):
    sys.path.insert(0, str(Path(project) / "lib" / "common"))
    import wsconfig
    return wsconfig.load(Path(project))


def _snap_name(cfg):
    board = cfg["silicon"]["board"]
    name = f"{board}-kernel"
    if not SNAP_NAME_RE.match(name) or len(name) > 40:
        raise RenderError(f"silicon.board '{board}' does not give a valid snap name ('{name}'): "
                          "use lowercase letters, digits and single hyphens")
    return name


def check_name(project):
    """Fail early (before any build) when silicon.board cannot name a snap."""
    _snap_name(_load_cfg(project))


def render(project, kernel_dir, template, out_dir):
    project, kernel_dir, out_dir = Path(project), Path(kernel_dir), Path(out_dir)
    cfg = _load_cfg(project)
    meta = json.loads((kernel_dir / "metadata" / "build.json").read_text())
    board = cfg["silicon"]["board"]
    name = _snap_name(cfg)
    if len(meta["version"]) > 32:
        raise RenderError(f"snap version '{meta['version']}' is longer than 32 characters")
    flavour = cfg["kernel"]["flavour"]
    suffix = f"-{flavour}"
    if not meta["kver"].endswith(suffix):
        raise RenderError(f"kver {meta['kver']} does not end in {suffix}")
    values = {
        "name": name,
        "version": meta["version"],
        "board": board,
        "release": cfg["ubuntu"]["release"],
        "flavour": flavour,
        "abinumber": meta["kver"][: -len(suffix)],
    }
    try:
        text = _Template(Path(template).read_text()).substitute(values)
    except (KeyError, ValueError) as e:
        raise RenderError(f"template {template}: bad placeholder ({e})")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "snapcraft.yaml").write_text(text)
    (out_dir / "kernel.yaml").write_text(KERNEL_YAML)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--check-name", action="store_true",
                        help="only check that silicon.board gives a valid snap name")
    for opt in ("--kernel-dir", "--template", "--out-dir"):
        parser.add_argument(opt, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.check_name:
            check_name(args.project)
            return 0
        if not (args.kernel_dir and args.template and args.out_dir):
            parser.error("--kernel-dir, --template and --out-dir are required")
        render(args.project, args.kernel_dir, args.template, args.out_dir)
    except RenderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
