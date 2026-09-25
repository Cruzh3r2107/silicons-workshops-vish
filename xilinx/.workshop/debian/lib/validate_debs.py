#!/usr/bin/env python3
"""Validate Ubuntu kernel .debs in out/deb against the validated kernel outputs."""
import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path


class DebError(Exception):
    pass


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fields(deb):
    r = subprocess.run(["dpkg-deb", "-f", str(deb), "Package", "Version", "Architecture"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise DebError(r.stderr.strip())
    return dict(line.split(": ", 1) for line in r.stdout.splitlines() if ": " in line)


def _walk(deb, want=None):
    """Return (member names, bytes of member `want` or None), streaming the data tar."""
    proc = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(deb)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    names, data = [], None
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for info in tar:
                name = info.name[2:] if info.name.startswith("./") else info.name
                names.append(name)
                if want is not None and name == want and info.isfile():
                    data = tar.extractfile(info).read()
    except tarfile.TarError as e:
        raise DebError(str(e))
    finally:
        proc.stdout.close()
        stderr = proc.stderr.read().decode()
        if proc.wait() != 0:
            raise DebError(stderr.strip())
    return names, data


def check(deb_dir, kernel_dir, cfg, dts_subdir):
    deb_dir, kernel_dir = Path(deb_dir), Path(kernel_dir)
    meta = json.loads((kernel_dir / "metadata" / "build.json").read_text())
    kver, version = meta["kver"], meta["version"]
    debs = sorted(deb_dir.glob("*.deb"))
    if not debs:
        return [f"{deb_dir}: no .deb packages"]

    errors, packages, contents = [], {}, {}
    record = deb_dir / "metadata" / "packages.json"
    try:
        recorded = {e["file"]: e["sha256"] for e in json.loads(record.read_text())}
    except (OSError, ValueError, KeyError, TypeError) as e:
        return [f"{record}: unreadable package record ({e})"]
    present = {deb.name for deb in debs}
    for name in sorted(set(recorded) - present):
        errors.append(f"{name}: recorded in packages.json but missing from {deb_dir}")
    for name in sorted(present - set(recorded)):
        errors.append(f"{name}: not recorded in packages.json")
    for name in sorted(present & set(recorded)):
        if _sha256_file(deb_dir / name) != recorded[name]:
            errors.append(f"{name}: changed since kernel-build-debs recorded it")
    image_pkg, modules_pkg = f"linux-image-{kver}", f"linux-modules-{kver}"
    vmlinuz = f"boot/vmlinuz-{kver}"
    image_data = None
    for deb in debs:
        try:
            fields = _fields(deb)
            names, data = _walk(deb, vmlinuz if fields.get("Package") == image_pkg else None)
        except DebError as e:
            errors.append(f"{deb.name}: unreadable package ({e})")
            continue
        pkg = fields.get("Package", "")
        packages[pkg] = deb
        contents[pkg] = names
        if fields.get("Architecture") != "arm64":
            errors.append(f"{deb.name}: Architecture is {fields.get('Architecture')}, expected arm64")
        if fields.get("Version") != version:
            errors.append(f"{deb.name}: Version is {fields.get('Version')}, expected {version}")
        if pkg == image_pkg:
            image_data = data

    for required in (image_pkg, modules_pkg):
        if required not in packages:
            errors.append(f"required package {required} was not built")

    if image_pkg in packages:
        expected = (kernel_dir / "image" / "Image.gz").read_bytes()
        if image_data is None:
            errors.append(f"{packages[image_pkg].name}: {vmlinuz} missing")
        elif _sha256_bytes(image_data) != _sha256_bytes(expected):
            errors.append(f"{packages[image_pkg].name}: {vmlinuz} differs from "
                          f"{kernel_dir}/image/Image.gz (kernel was rebuilt or diverged; run kernel-clean, "
                          "then kernel-build-debs)")

    all_paths = {p for names in contents.values() for p in names}
    firmware = f"lib/firmware/{kver}/device-tree"
    for dtb in cfg["kernel"]["device_trees"]:
        if f"{firmware}/{dtb}" not in all_paths:
            errors.append(f"device tree {dtb} not packaged under /{firmware}/")
    for overlay in cfg["overlays"]:
        rel = f"{firmware}/{dts_subdir}/{Path(overlay).stem}.dtbo"
        if rel not in all_paths:
            errors.append(f"overlay {overlay} not packaged as /{rel}")

    if modules_pkg in contents:
        prefixes = (f"lib/modules/{kver}/", f"usr/lib/modules/{kver}/")
        if not any(p.startswith(prefixes) for p in contents[modules_pkg]):
            errors.append(f"{packages[modules_pkg].name}: no files under /lib/modules/{kver}/")
    return errors


def write_metadata(deb_dir):
    deb_dir = Path(deb_dir)
    entries = []
    for deb in sorted(deb_dir.glob("*.deb")):
        fields = _fields(deb)
        entries.append({
            "file": deb.name,
            "package": fields["Package"],
            "version": fields["Version"],
            "architecture": fields["Architecture"],
            "sha256": _sha256_file(deb),
        })
    (deb_dir / "metadata").mkdir(exist_ok=True)
    (deb_dir / "metadata" / "packages.json").write_text(json.dumps(entries, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--project", required=True)
    c.add_argument("--deb-dir", required=True, type=Path)
    c.add_argument("--kernel-dir", required=True, type=Path)
    c.add_argument("--dts-subdir", required=True)
    sub.add_parser("metadata").add_argument("--deb-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "metadata":
        write_metadata(args.deb_dir)
        return 0
    sys.path.insert(0, str(Path(args.project) / "lib" / "common"))
    import wsconfig
    cfg = wsconfig.load(Path(args.project))
    try:
        errors = check(args.deb_dir, args.kernel_dir, cfg, args.dts_subdir)
    except (OSError, ValueError, KeyError) as e:
        errors = [f"cannot validate packages: {e}"]
    for err in errors:
        print(f"validation: {err}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
