import gzip
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.helpers import REPO, make_project, update_config

spec = importlib.util.spec_from_file_location("validate_snap", REPO / ".workshop/snap/lib/validate_snap.py")
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)
sys.path.insert(0, str(REPO / "lib" / "common"))
import wsconfig  # noqa: E402

KVER = "6.8.0-1036-xilinx"
VERSION = "6.8.0-1036.37+workshop1"


class ValidateSnapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = make_project(self.tmp)
        self.kernel = self.tmp / "out/kernel"
        (self.kernel / "metadata").mkdir(parents=True)
        (self.kernel / "image").mkdir()
        self.image = gzip.compress(b"kernel" * 100, mtime=0)
        (self.kernel / "image/Image.gz").write_bytes(self.image)
        (self.kernel / "metadata/build.json").write_text(json.dumps({"kver": KVER, "version": VERSION}))
        self.root = self.tmp / "root"
        files = {
            "kernel.img": self.image,
            "vmlinuz": self.image,
            "initrd.img": b"initrd",
            f"modules/{KVER}/modules.dep": b"kernel/test.ko:\n",
            "dtbs/xilinx/board.dtb": b"\xd0\x0d\xfe\xed" + b"\0" * 60,
            "meta/kernel.yaml": yaml.safe_dump({"assets": {"dtbs": {"update": True, "content": ["dtbs/"]}}}).encode(),
            "meta/snap.yaml": yaml.safe_dump({"name": "kv260-kernel", "version": VERSION, "type": "kernel",
                                              "architectures": ["arm64"]}).encode(),
        }
        for rel, data in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def pack(self):
        snap = self.tmp / "kv260-kernel.snap"
        snap.unlink(missing_ok=True)
        subprocess.run(["mksquashfs", str(self.root), str(snap), "-noappend", "-quiet"],
                       check=True, stdout=subprocess.DEVNULL)
        return snap

    def errors(self):
        return vs.check(self.pack(), self.kernel, wsconfig.load(self.proj), "xilinx")

    def assertError(self, fragment):
        errs = self.errors()
        self.assertTrue(any(fragment in e for e in errs), f"{fragment!r} not in {errs}")

    def test_valid_snap(self):
        self.assertEqual(self.errors(), [])

    def test_not_a_snap(self):
        bad = self.tmp / "bad.snap"
        bad.write_bytes(b"nope")
        errs = vs.check(bad, self.kernel, wsconfig.load(self.proj), "xilinx")
        self.assertTrue(any("cannot unpack" in e for e in errs), errs)

    def test_wrong_type(self):
        (self.root / "meta/snap.yaml").write_text(yaml.safe_dump(
            {"name": "kv260-kernel", "version": VERSION, "type": "app", "architectures": ["arm64"]}))
        self.assertError("type is app")

    def test_wrong_snap_name_fails(self):
        update_config(self.proj, lambda c: c["silicon"].update(board="kr260"))
        self.assertError("name is kv260-kernel, expected kr260-kernel")

    def test_foreign_kernel_image_fails(self):
        (self.root / "kernel.img").write_bytes(gzip.compress(b"archive kernel", mtime=0))
        self.assertError("kernel.img differs from")

    def test_missing_initrd(self):
        (self.root / "initrd.img").unlink()
        self.assertError("initrd.img missing or empty")

    def test_missing_modules_dep(self):
        (self.root / f"modules/{KVER}/modules.dep").unlink()
        self.assertError("modules.dep missing")

    def test_missing_dtb_in_snap_fails(self):
        update_config(self.proj, lambda c: c["kernel"].update(device_trees=["xilinx/board.dtb", "xilinx/other.dtb"]))
        self.assertError("dtbs/xilinx/other.dtb missing")

    def test_missing_overlay_in_snap_fails(self):
        (self.proj / "overlays/extra.dtso").write_text("x")
        update_config(self.proj, lambda c: c.update(overlays=["overlays/extra.dtso"]))
        self.assertError("dtbs/xilinx/extra.dtbo missing")

    def test_missing_dtbs_asset(self):
        (self.root / "meta/kernel.yaml").write_text("assets: {}\n")
        self.assertError("dtbs asset")

    def test_metadata(self):
        snap = self.pack()
        vs.write_metadata(snap, self.kernel)
        meta = json.loads((snap.parent / "metadata/snap.json").read_text())
        self.assertEqual(meta["version"], VERSION)
        self.assertEqual(meta["kver"], KVER)


if __name__ == "__main__":
    unittest.main()
