"""kernel-build-snap orchestration with stubbed sudo, snapcraft and kernel-build-debs."""
import gzip
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, make_project, run, sdk_env, update_config

KVER = "6.8.0-1036-xilinx"
VERSION = "6.8.0-1036.37+workshop1"

# sudo: log the command, drop sudo's own options, run it as the current user.
SUDO = """#!/bin/sh
printf '%s\\n' "$*" >>"$STUB_LOG"
while [ $# -gt 0 ]; do case "$1" in -*) shift ;; *) break ;; esac; done
exec "$@"
"""

# apt-get: nothing to update in tests.
APT_GET = """#!/bin/sh
exit 0
"""

# kernel-build-debs: produce the state and outputs the Snap SDK consumes.
KERNEL_BUILD_DEBS = r"""#!/usr/bin/env python3
import gzip, json, os, subprocess
from pathlib import Path
proj = Path(os.environ["PROJECT_DIR"])
kernel = proj / "out/kernel"
(kernel / "image").mkdir(parents=True, exist_ok=True)
(kernel / "metadata").mkdir(exist_ok=True)
(kernel / "image/Image.gz").write_bytes(gzip.compress(b"kernel" * 100, mtime=0))
(kernel / "metadata/build.json").write_text(json.dumps(
    {"kver": "6.8.0-1036-xilinx", "version": "6.8.0-1036.37+workshop1"}))
root = proj / "build/stub-deb"
(root / "DEBIAN").mkdir(parents=True, exist_ok=True)
(root / "DEBIAN/control").write_text(
    "Package: linux-image-6.8.0-1036-xilinx\nVersion: 6.8.0-1036.37+workshop1\n"
    "Architecture: arm64\nMaintainer: T <t@example.com>\nDescription: stub\n")
(proj / "out/deb").mkdir(parents=True, exist_ok=True)
subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root),
                str(proj / "out/deb/linux-image-6.8.0-1036-xilinx_6.8.0-1036.37+workshop1_arm64.deb")],
               check=True, stdout=subprocess.DEVNULL)
(proj / "build/state").mkdir(parents=True, exist_ok=True)
(proj / "build/state/debs.fingerprint").write_text("debs-fp\n")
print("==> Debian packages are up to date and valid")
"""

# snapcraft: build a valid kernel snap from the rendered project, or fail /
# get interrupted on request.
SNAPCRAFT = r"""#!/usr/bin/env python3
import gzip, os, shutil, signal, subprocess, sys, time
from pathlib import Path
import yaml
with open(os.environ["STUB_LOG"], "a") as log:
    log.write("SNAPCRAFT-STUB " + " ".join(sys.argv[1:]) + "\n")
# Like the real (snap-confined) snapcraft: output written to an inherited
# regular-file descriptor is lost; only pipes/ttys receive it.
import stat
if not stat.S_ISREG(os.fstat(1).st_mode):
    print("PLUGIN-OUTPUT: building kernel and initrd parts", flush=True)
if os.environ.get("FAKE_SNAPCRAFT_FAIL"):
    Path("parts").mkdir(exist_ok=True)
    sys.exit("snapcraft: simulated failure")
if os.environ.get("FAKE_SNAPCRAFT_TERM"):
    os.kill(os.getppid(), signal.SIGTERM)
    time.sleep(1)
    sys.exit(1)
doc = yaml.safe_load(Path("snapcraft.yaml").read_text())
proj = Path(os.environ["PROJECT_DIR"])
root = Path("stub-root")
shutil.rmtree(root, ignore_errors=True)
image = (proj / "out/kernel/image/Image.gz").read_bytes()
files = {
    "kernel.img": image, "vmlinuz": image, "initrd.img": b"initrd",
    "modules/6.8.0-1036-xilinx/modules.dep": b"kernel/test.ko:\n",
    "dtbs/xilinx/board.dtb": b"\xd0\x0d\xfe\xed" + b"\0" * 60,
    "meta/kernel.yaml": Path("kernel.yaml").read_bytes(),
    "meta/snap.yaml": yaml.safe_dump({"name": doc["name"], "version": doc["version"],
                                      "type": "kernel", "architectures": ["arm64"]}).encode(),
}
for rel, data in files.items():
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
subprocess.run(["mksquashfs", str(root), f"{doc['name']}_{doc['version']}_arm64.snap",
                "-noappend", "-quiet"], check=True, stdout=subprocess.DEVNULL)
"""


class SnapMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = make_project(self.tmp)
        self.stubs = self.tmp / "stubs"
        self.stubs.mkdir()
        for name, text in (("sudo", SUDO), ("apt-get", APT_GET),
                           ("kernel-build-debs", KERNEL_BUILD_DEBS), ("snapcraft", SNAPCRAFT)):
            (self.stubs / name).write_text(text)
            (self.stubs / name).chmod(0o755)
        self.log = self.tmp / "stub.log"
        self.log.touch()
        self.apt_source = self.tmp / "workshop-local.sources"
        self.apt_pin = self.tmp / "workshop-local.pin"

    def build(self, **extra):
        env = {
            "PATH": os.pathsep.join([str(self.stubs), sdk_env(self.proj)["PATH"]]),
            "STUB_LOG": str(self.log),
            "AARCH64_PROBE": "/bin/true",
            "APT_SOURCE": str(self.apt_source),
            "APT_PIN": str(self.apt_pin),
        }
        env.update(extra)
        return run(["kernel-build-snap"], self.proj, env)

    def snapcraft_runs(self):
        return [line for line in self.log.read_text().splitlines() if line.startswith("SNAPCRAFT-STUB ")]

    def test_build_then_reuse(self):
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kernel-build-snap complete", r.stdout)
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("up to date", r.stdout)
        self.assertEqual(len(self.snapcraft_runs()), 1)

    def test_invalid_board_rejected_before_building(self):
        update_config(self.proj, lambda c: c["silicon"].update(board="KV260"))
        r = self.build()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("silicon.board", r.stderr)
        self.assertFalse((self.proj / "out/deb").exists())

    def test_missing_snap_rebuilds(self):
        self.assertEqual(self.build().returncode, 0)
        for snap in (self.proj / "out/snap").glob("*.snap"):
            snap.unlink()
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("kernel-build-snap complete", r.stdout)
        self.assertEqual(len(self.snapcraft_runs()), 2)

    def test_board_rename_rebuilds(self):
        self.assertEqual(self.build().returncode, 0)
        update_config(self.proj, lambda c: c["silicon"].update(board="kr260"))
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(list((self.proj / "out/snap").glob("kr260-kernel_*.snap")))

    def test_snapcraft_runs_verbose_so_its_output_reaches_the_stage_log(self):
        self.assertEqual(self.build().returncode, 0)
        self.assertIn("--verbosity=verbose", self.snapcraft_runs()[0])
        self.assertIn("PLUGIN-OUTPUT", (self.proj / "build/logs/snapcraft.log").read_text())

    def test_snapcraft_failure_status_survives_the_output_pipe(self):
        r = self.build(FAKE_SNAPCRAFT_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("PLUGIN-OUTPUT", (self.proj / "build/logs/snapcraft.log").read_text())

    def test_failed_snapcraft_restores_ownership_and_unpublishes_archive(self):
        r = self.build(FAKE_SNAPCRAFT_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('stage "snapcraft" failed', r.stderr)
        self.assertIn(f"chown -R {os.getuid()}:{os.getgid()} {self.proj}/build/snap/project",
                      self.log.read_text())
        self.assertFalse(self.apt_source.exists())
        self.assertFalse(self.apt_pin.exists())

    def test_interrupted_snapcraft_unpublishes_archive(self):
        r = self.build(FAKE_SNAPCRAFT_TERM="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.apt_source.exists())
        self.assertFalse(self.apt_pin.exists())


if __name__ == "__main__":
    unittest.main()
