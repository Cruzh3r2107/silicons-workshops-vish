#!/usr/bin/env python3
"""Validate the normalized Kernel SDK outputs (out/kernel) and record build metadata."""
import argparse
import gzip
import hashlib
import json
import lzma
import re
import subprocess
import sys
from pathlib import Path

ARM64_MAGIC = b"ARM\x64"   # arm64 Image header magic at offset 56
FDT_MAGIC = b"\xd0\x0d\xfe\xed"
EM_AARCH64 = 183


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_image(path):
    if not path.is_file() or path.stat().st_size == 0:
        return [f"{path}: kernel image missing or empty"]
    try:
        with gzip.open(path) as f:
            head = f.read(64)
    except (OSError, EOFError) as e:
        return [f"{path}: not a valid gzip-compressed image ({e})"]
    if len(head) < 64 or head[56:60] != ARM64_MAGIC:
        return [f"{path}: not an ARM64 Linux kernel Image"]
    return []


def _check_dtb(path, root_compatible):
    if not path.is_file() or path.stat().st_size == 0:
        return [f"{path}: device tree missing or empty"]
    if path.read_bytes()[:4] != FDT_MAGIC:
        return [f"{path}: not a flattened device tree"]
    r = subprocess.run(["dtc", "-q", "-I", "dtb", "-O", "dts", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [f"{path}: dtc cannot parse it: {r.stderr.strip()}"]
    if root_compatible:
        # dtc prints root properties first, indented by one tab, and may join a
        # string list into one literal with "\0" separators.
        m = re.search(r"^\tcompatible = (.+);$", r.stdout, re.M)
        values = []
        for literal in re.findall(r'"([^"]*)"', m.group(1) if m else ""):
            values += literal.split("\\0")
        if root_compatible not in values:
            return [f"{path}: root compatible does not include {root_compatible}"]
    return []


def _module_head(path):
    if path.name.endswith(".zst"):
        return subprocess.run(["zstd", "-dc", str(path)], capture_output=True).stdout[:64]
    if path.name.endswith(".xz"):
        with lzma.open(path) as f:
            return f.read(64)
    return path.read_bytes()[:64]


def _check_modules(mod_dir):
    if not mod_dir.is_dir():
        return [f"{mod_dir}: modules directory missing"]
    mods = sorted(p for p in mod_dir.rglob("*")
                  if p.is_file() and p.name.endswith((".ko", ".ko.zst", ".ko.xz")))
    if not mods:
        return [f"{mod_dir}: no kernel modules found"]
    dep = mod_dir / "modules.dep"
    if not dep.is_file() or not dep.read_text().strip():
        return [f"{dep}: missing or empty (depmod did not run)"]
    head = _module_head(mods[0])
    if head[:4] != b"\x7fELF" or int.from_bytes(head[18:20], "little") != EM_AARCH64:
        return [f"{mods[0]}: not an AArch64 ELF object"]
    return []


def _check_config(path, wanted):
    if not path.is_file():
        return [f"{path}: final kernel config missing"]
    lines = set(path.read_text().splitlines())
    errors = []
    for key, value in wanted.items():
        value = str(value)
        if value == "n":
            ok = not any(line.startswith(f"{key}=") for line in lines)
        else:
            ok = f"{key}={value}" in lines or f'{key}="{value}"' in lines
        if not ok:
            errors.append(f"{path}: {key} is not set to {value}")
    return errors


def _check_hashes(out_dir, files):
    if not files:
        return [f"{out_dir}/metadata/build.json: no staged files recorded"]
    errors = []
    for rel, digest in files.items():
        p = out_dir / rel
        if not p.is_file() or _sha256(p) != digest:
            errors.append(f"{p}: missing or changed since kernel-build staged it")
    return errors


def check(out_dir, cfg, root_compatible, dts_subdir):
    out_dir = Path(out_dir)
    meta_path = out_dir / "metadata" / "build.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError) as e:
        return [f"{meta_path}: unreadable build metadata ({e})"]
    errors = []
    flavour = cfg["kernel"]["flavour"]
    kver = meta.get("kver", "")
    if not re.fullmatch(rf"\d+\.\d+\.\d+-\d+-{re.escape(flavour)}", kver):
        errors.append(f"{meta_path}: kver '{kver}' does not match <version>-<abi>-{flavour}")
    errors += _check_image(out_dir / "image" / "Image.gz")
    for dtb in cfg["kernel"]["device_trees"]:
        errors += _check_dtb(out_dir / "dtbs" / dtb, root_compatible)
    for overlay in cfg["overlays"]:
        errors += _check_dtb(out_dir / "dtbs" / dts_subdir / "overlays" / (Path(overlay).stem + ".dtbo"), None)
    errors += _check_modules(out_dir / "modules" / "lib" / "modules" / kver)
    errors += _check_config(out_dir / "config", cfg["kernel"]["config"])
    errors += _check_hashes(out_dir, meta.get("files", {}))
    return errors


def write_metadata(out_dir, cfg, kver, version, commit, fp):
    out_dir = Path(out_dir)
    meta_dir = out_dir / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    files = {
        str(p.relative_to(out_dir)): _sha256(p)
        for p in sorted(out_dir.rglob("*"))
        if p.is_file() and not p.is_symlink() and meta_dir not in p.parents
    }
    meta = {
        "kver": kver,
        "version": version,
        "repository": cfg["kernel"]["source"]["repository"],
        "ref": cfg["kernel"]["source"]["ref"],
        "commit": commit,
        "patches": cfg["patches"],
        "overlays": cfg["overlays"],
        "device_trees": cfg["kernel"]["device_trees"],
        "fingerprint": fp,
        "files": files,
    }
    (meta_dir / "build.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")


def _load_cfg(project):
    sys.path.insert(0, str(Path(project) / "lib" / "common"))
    import wsconfig
    return wsconfig.load(Path(project))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    m = sub.add_parser("metadata")
    for p in (c, m):
        p.add_argument("--project", required=True)
        p.add_argument("--out-dir", required=True, type=Path)
    c.add_argument("--root-compatible", required=True)
    c.add_argument("--dts-subdir", required=True)
    for opt in ("--kver", "--version", "--commit", "--fingerprint"):
        m.add_argument(opt, required=True)
    args = parser.parse_args(argv)
    cfg = _load_cfg(args.project)
    if args.cmd == "metadata":
        write_metadata(args.out_dir, cfg, args.kver, args.version, args.commit, args.fingerprint)
        return 0
    errors = check(args.out_dir, cfg, args.root_compatible, args.dts_subdir)
    for err in errors:
        print(f"validation: {err}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
