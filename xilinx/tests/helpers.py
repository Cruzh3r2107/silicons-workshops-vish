"""Shared helpers for Workshop SDK tests."""
import os
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG = """\
schema: 1
silicon:
  vendor: amd-xilinx
  family: zynqmp
  board: kv260
ubuntu:
  release: {release}
kernel:
  source:
    repository: {repository}
    ref: {ref}
  flavour: xilinx
  config: {{}}
  device_trees:
    - xilinx/board.dtb
patches: []
overlays: []
"""


def host_release():
    for line in Path("/etc/os-release").read_text().splitlines():
        if line.startswith("VERSION_CODENAME="):
            return line.split("=", 1)[1].strip('"')
    raise RuntimeError("VERSION_CODENAME missing from /etc/os-release")


def make_project(root, repository="https://example.invalid/linux.git",
                 ref="Ubuntu-xilinx-6.8.0-1036.37", text=None):
    """Create a throwaway project dir that uses this repo's lib/ and .workshop/."""
    proj = Path(root) / "project"
    (proj / "patches").mkdir(parents=True)
    (proj / "overlays").mkdir()
    (proj / "lib").symlink_to(REPO / "lib")
    (proj / ".workshop").symlink_to(REPO / ".workshop")
    if text is None:
        text = DEFAULT_CONFIG.format(release=host_release(), repository=repository, ref=ref)
    (proj / "project.yaml").write_text(text)
    return proj


def update_config(proj, fn):
    path = Path(proj) / "project.yaml"
    cfg = yaml.safe_load(path.read_text())
    fn(cfg)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))


def sdk_env(proj, extra=None):
    env = dict(os.environ)
    env["PROJECT_DIR"] = str(proj)
    bins = [str(REPO / ".workshop" / sdk / "bin") for sdk in ("kernel", "debian", "snap")]
    env["PATH"] = os.pathsep.join(bins + [env["PATH"]])
    env.update(extra or {})
    return env


def run(cmd, proj, extra_env=None):
    return subprocess.run(cmd, env=sdk_env(proj, extra_env), capture_output=True, text=True)
