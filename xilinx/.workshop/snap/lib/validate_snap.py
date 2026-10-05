#!/usr/bin/env python3
"""Validate the Ubuntu Core kernel snap in out/snap against the validated kernel outputs."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _nonempty(path):
    return path.is_file() and path.stat().st_size > 0


def check(snap, kernel_dir, cfg, dts_subdir):
    snap, kernel_dir = Path(snap), Path(kernel_dir)
    meta = json.loads((kernel_dir / "metadata" / "build.json").read_text())
    kver, version = meta["kver"], meta["version"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "snap"
        # Extract only what is checked; the modules tree alone is thousands of files.
        wanted = ["meta", "kernel.img", "vmlinuz", "initrd.img", "dtbs",
                  f"modules/{kver}/modules.dep"]
        r = subprocess.run(["unsquashfs", "-no-progress", "-d", str(root), str(snap), *wanted],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return [f"{snap.name}: cannot unpack ({r.stderr.strip()})"]
        errors = []
        try:
            snap_yaml = yaml.safe_load((root / "meta/snap.yaml").read_text()) or {}
        except (OSError, yaml.YAMLError) as e:
            return [f"{snap.name}: meta/snap.yaml unreadable ({e})"]
        expected_name = f"{cfg['silicon']['board']}-kernel"
        if snap_yaml.get("name") != expected_name:
            errors.append(f"{snap.name}: name is {snap_yaml.get('name')}, expected {expected_name}")
        if snap_yaml.get("type") != "kernel":
            errors.append(f"{snap.name}: type is {snap_yaml.get('type')}, expected kernel")
        if snap_yaml.get("architectures") != ["arm64"]:
            errors.append(f"{snap.name}: architectures are {snap_yaml.get('architectures')}, expected [arm64]")
        if str(snap_yaml.get("version")) != version:
            errors.append(f"{snap.name}: version is {snap_yaml.get('version')}, expected {version}")

        expected = _sha256(kernel_dir / "image" / "Image.gz")
        for image in ("kernel.img", "vmlinuz"):
            p = root / image
            if not _nonempty(p):
                errors.append(f"{snap.name}: {image} missing or empty")
            elif _sha256(p) != expected:
                errors.append(f"{snap.name}: {image} differs from {kernel_dir}/image/Image.gz "
                              "(the snap did not use the Workshop's debs)")
        if not _nonempty(root / "initrd.img"):
            errors.append(f"{snap.name}: initrd.img missing or empty")
        if not (root / "modules" / kver / "modules.dep").is_file():
            errors.append(f"{snap.name}: modules/{kver}/modules.dep missing")
        for dtb in cfg["kernel"]["device_trees"]:
            if not _nonempty(root / "dtbs" / dtb):
                errors.append(f"{snap.name}: dtbs/{dtb} missing")
        for overlay in cfg["overlays"]:
            rel = f"dtbs/{dts_subdir}/{Path(overlay).stem}.dtbo"
            if not _nonempty(root / rel):
                errors.append(f"{snap.name}: {rel} missing")
        try:
            kernel_yaml = yaml.safe_load((root / "meta/kernel.yaml").read_text()) or {}
            content = kernel_yaml["assets"]["dtbs"]["content"]
        except (OSError, yaml.YAMLError, KeyError, TypeError):
            content = None
        if not content or "dtbs/" not in content:
            errors.append(f"{snap.name}: meta/kernel.yaml does not declare the dtbs asset with dtbs/ content")
        return errors


def write_metadata(snap, kernel_dir):
    snap, kernel_dir = Path(snap), Path(kernel_dir)
    meta = json.loads((kernel_dir / "metadata" / "build.json").read_text())
    (snap.parent / "metadata").mkdir(exist_ok=True)
    (snap.parent / "metadata" / "snap.json").write_text(json.dumps({
        "file": snap.name,
        "name": snap.name.split("_", 1)[0],
        "version": meta["version"],
        "kver": meta["kver"],
        "sha256": _sha256(snap),
    }, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--project", required=True)
    c.add_argument("--snap", required=True, type=Path)
    c.add_argument("--kernel-dir", required=True, type=Path)
    c.add_argument("--dts-subdir", required=True)
    m = sub.add_parser("metadata")
    m.add_argument("--snap", required=True, type=Path)
    m.add_argument("--kernel-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "metadata":
        write_metadata(args.snap, args.kernel_dir)
        return 0
    sys.path.insert(0, str(Path(args.project) / "lib" / "common"))
    import wsconfig
    errors = check(args.snap, args.kernel_dir, wsconfig.load(Path(args.project)), args.dts_subdir)
    for err in errors:
        print(f"validation: {err}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
