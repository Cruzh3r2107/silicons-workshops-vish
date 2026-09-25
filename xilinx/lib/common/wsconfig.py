#!/usr/bin/env python3
"""Load, validate and query the Workshop project configuration (project.yaml)."""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import yaml

SCHEMA_VERSION = 1

# Expected shape: a dict is a nested mapping; a type is a leaf.
SCHEMA = {
    "schema": int,
    "silicon": {"vendor": str, "family": str, "board": str},
    "ubuntu": {"release": str},
    "kernel": {
        "source": {"repository": str, "ref": str},
        "flavour": str,
        "config": dict,
        "device_trees": list,
    },
    "patches": list,
    "overlays": list,
}

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~-]*$")
CONFIG_KEY_RE = re.compile(r"^CONFIG_[A-Z0-9_]+$")
FLAVOUR_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
BRANCH_NAMES = {"master", "main", "master-next", "main-next", "HEAD"}


class ConfigError(Exception):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


def host_release():
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("VERSION_CODENAME="):
            return line.split("=", 1)[1].strip('"') or None
    return None


def load(project_dir):
    path = Path(project_dir) / "project.yaml"
    try:
        data = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ConfigError([f"{path} not found"])
    except yaml.YAMLError as e:
        raise ConfigError([f"invalid YAML: {e}"])
    if not isinstance(data, dict):
        raise ConfigError(["top level must be a mapping"])
    return data


def _check_shape(node, schema, prefix, errors):
    if not isinstance(node, dict):
        errors.append(f"{prefix.rstrip('.') or 'project.yaml'}: expected a mapping")
        return
    for key in node:
        if key not in schema:
            errors.append(f"{prefix}{key}: unknown key")
    for key, sub in schema.items():
        full = f"{prefix}{key}"
        if key not in node:
            errors.append(f"{full}: required key missing")
            continue
        value = node[key]
        if isinstance(sub, dict):
            _check_shape(value, sub, full + ".", errors)
        elif sub is int and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append(f"{full}: expected an integer")
        elif sub is str and (not isinstance(value, str) or not value.strip()):
            errors.append(f"{full}: expected a non-empty string")
        elif sub is list and not isinstance(value, list):
            errors.append(f"{full}: expected a list")
        elif sub is dict and not isinstance(value, dict):
            errors.append(f"{full}: expected a mapping")


def _safe_rel(path):
    return (isinstance(path, str) and path and not path.startswith("/")
            and ".." not in Path(path).parts and not re.search(r"\s", path))


def _check_files(entries, project_dir, key, suffix, errors):
    names = set()
    for entry in entries:
        if not _safe_rel(entry) or not entry.startswith(f"{key}/"):
            errors.append(f"{key}: '{entry}' must be a relative path under {key}/ without spaces")
            continue
        if suffix and not entry.endswith(suffix):
            errors.append(f"{key}: '{entry}' must end in {suffix}")
        if not (Path(project_dir) / entry).is_file():
            errors.append(f"{key}: '{entry}' does not exist")
        name = Path(entry).name
        if name in names:
            errors.append(f"{key}: '{name}' listed twice")
        names.add(name)


def validate(cfg, project_dir, base_release=None):
    errors = []
    _check_shape(cfg, SCHEMA, "", errors)
    if errors:
        return errors

    if cfg["schema"] != SCHEMA_VERSION:
        errors.append(f"schema: unsupported version {cfg['schema']} (expected {SCHEMA_VERSION})")

    if base_release and cfg["ubuntu"]["release"] != base_release:
        errors.append(f"ubuntu.release: '{cfg['ubuntu']['release']}' does not match the "
                      f"Workshop base '{base_release}'")

    source = cfg["kernel"]["source"]
    if re.search(r"\s", source["repository"]):
        errors.append("kernel.source.repository: must not contain whitespace")
    ref = source["ref"]
    if ref in BRANCH_NAMES or ref.startswith(("refs/heads/", "origin/")):
        errors.append(f"kernel.source.ref: '{ref}' is a branch; use a tag or a 40-character commit SHA")
    elif not (SHA_RE.match(ref) or TAG_RE.match(ref)):
        errors.append(f"kernel.source.ref: '{ref}' is not a tag name or 40-character commit SHA")

    if not FLAVOUR_RE.match(cfg["kernel"]["flavour"]):
        errors.append(f"kernel.flavour: '{cfg['kernel']['flavour']}' is not a valid flavour name")

    for key, value in cfg["kernel"]["config"].items():
        if not isinstance(key, str) or not CONFIG_KEY_RE.match(key):
            errors.append(f"kernel.config.{key}: key must look like CONFIG_NAME")
        elif isinstance(value, bool):
            errors.append(f"kernel.config.{key}: YAML read this as a boolean; quote the value "
                          f"(for example 'y' or 'n')")
        elif isinstance(value, (int, float)):
            # YAML 1.1 rewrites 0x10, 010 and 1:30 as 16, 8 and 90; accepting
            # any number would silently change hex/octal Kconfig values.
            errors.append(f"kernel.config.{key}: YAML read this as the number {value!r}; quote the "
                          f"value exactly as Kconfig expects (for example '0x10' or '250')")
        elif not isinstance(value, str) or not value.strip():
            errors.append(f"kernel.config.{key}: expected y, m, n or a value")

    dtbs = cfg["kernel"]["device_trees"]
    if not dtbs:
        errors.append("kernel.device_trees: at least one device tree is required")
    seen = set()
    for dtb in dtbs:
        if not _safe_rel(dtb) or not dtb.endswith(".dtb"):
            errors.append(f"kernel.device_trees: '{dtb}' must be a relative path ending in .dtb")
            continue
        if dtb in seen:
            errors.append(f"kernel.device_trees: '{dtb}' listed twice")
        seen.add(dtb)

    _check_files(cfg["patches"], project_dir, "patches", None, errors)
    _check_files(cfg["overlays"], project_dir, "overlays", ".dtso", errors)
    return errors


def get(cfg, dotted):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    return node


def _format(value):
    if isinstance(value, dict):
        return "\n".join(f"{k}={v}" for k, v in value.items())
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value)


def fingerprint(cfg, project_dir):
    h = hashlib.sha256()
    inputs = {"kernel": cfg["kernel"], "patches": cfg["patches"], "overlays": cfg["overlays"]}
    h.update(json.dumps(inputs, sort_keys=True).encode())
    for entry in cfg["patches"] + cfg["overlays"]:
        h.update(entry.encode() + b"\0" + (Path(project_dir) / entry).read_bytes())
    return h.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path,
                        default=Path(os.environ.get("PROJECT_DIR", "/project")))
    parser.add_argument("--base-release", default=None,
                        help="Workshop base series (default: from /etc/os-release)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    sub.add_parser("get").add_argument("key")
    sub.add_parser("fingerprint")
    args = parser.parse_args(argv)

    try:
        cfg = load(args.project)
    except ConfigError as e:
        for err in e.errors:
            print(f"project.yaml: {err}", file=sys.stderr)
        return 1
    errors = validate(cfg, args.project, args.base_release or host_release())
    if errors:
        for err in errors:
            print(f"project.yaml: {err}", file=sys.stderr)
        return 1

    if args.cmd == "get":
        try:
            text = _format(get(cfg, args.key))
        except KeyError:
            print(f"project.yaml: no such key '{args.key}'", file=sys.stderr)
            return 1
        sys.stdout.write(text + "\n" if text else "")
    elif args.cmd == "fingerprint":
        print(fingerprint(cfg, args.project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
