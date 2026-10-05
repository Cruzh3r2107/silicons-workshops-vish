import gzip
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, make_project, update_config

spec = importlib.util.spec_from_file_location(
    "validate_kernel", REPO / ".workshop/kernel/lib/validate_kernel.py")
vk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vk)

sys.path.insert(0, str(REPO / "lib" / "common"))
import wsconfig  # noqa: E402

KVER = "6.8.0-1036-xilinx"
BOARD_DTS = """/dts-v1/;
/ {
	compatible = "xlnx,zynqmp-smk-k26", "xlnx,zynqmp";
	#address-cells = <2>;
	#size-cells = <2>;
};
"""


def arm64_image():
    header = bytearray(64)
    header[56:60] = b"ARM\x64"
    return gzip.compress(bytes(header) + b"\0" * 256, mtime=0)


def aarch64_elf(machine=183):
    elf = bytearray(64)
    elf[0:4] = b"\x7fELF"
    elf[4], elf[5] = 2, 1
    elf[18:20] = machine.to_bytes(2, "little")
    return bytes(elf)


def dtc(src_text, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["dtc", "-q", "-@", "-I", "dts", "-O", "dtb", "-o", str(dest), "-"],
                   input=src_text.encode(), check=True)


class ValidateKernelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = make_project(self.tmp)
        self.out = self.tmp / "out/kernel"
        (self.out / "image").mkdir(parents=True)
        (self.out / "image/Image.gz").write_bytes(arm64_image())
        dtc(BOARD_DTS, self.out / "dtbs/xilinx/board.dtb")
        mods = self.out / "modules/lib/modules" / KVER
        (mods / "kernel").mkdir(parents=True)
        (mods / "kernel/test.ko").write_bytes(aarch64_elf())
        (mods / "modules.dep").write_text("kernel/test.ko:\n")
        (self.out / "config").write_text("CONFIG_ARCH_ZYNQMP=y\n")

    def cfg(self):
        return wsconfig.load(self.proj)

    def restage_and_check(self):
        cfg = self.cfg()
        vk.write_metadata(self.out, cfg, KVER, "6.8.0-1036.37+workshop1", "a" * 40, "f" * 64)
        return vk.check(self.out, cfg, "xlnx,zynqmp", "xilinx")

    def assertError(self, fragment):
        errs = self.restage_and_check()
        self.assertTrue(any(fragment in e for e in errs), f"{fragment!r} not in {errs}")

    def test_valid_outputs(self):
        self.assertEqual(self.restage_and_check(), [])

    def test_metadata_contents(self):
        self.restage_and_check()
        meta = json.loads((self.out / "metadata/build.json").read_text())
        self.assertEqual(meta["kver"], KVER)
        self.assertIn("image/Image.gz", meta["files"])
        self.assertEqual(meta["device_trees"], ["xilinx/board.dtb"])

    def test_not_arm64_image(self):
        (self.out / "image/Image.gz").write_bytes(gzip.compress(b"\0" * 128))
        self.assertError("not an ARM64 Linux kernel Image")

    def test_missing_dtb(self):
        (self.out / "dtbs/xilinx/board.dtb").unlink()
        self.assertError("board.dtb: device tree missing or empty")

    def test_wrong_root_compatible(self):
        dtc(BOARD_DTS.replace('"xlnx,zynqmp-smk-k26", "xlnx,zynqmp"', '"acme,board"'),
            self.out / "dtbs/xilinx/board.dtb")
        self.assertError("root compatible does not include xlnx,zynqmp")

    def test_missing_overlay(self):
        (self.proj / "overlays/extra.dtso").write_text("/dts-v1/;\n/plugin/;\n")
        update_config(self.proj, lambda c: c.update(overlays=["overlays/extra.dtso"]))
        self.assertError("extra.dtbo: device tree missing or empty")

    def test_wrong_module_machine(self):
        (self.out / f"modules/lib/modules/{KVER}/kernel/test.ko").write_bytes(aarch64_elf(62))
        self.assertError("not an AArch64 ELF object")

    def test_missing_modules_dep(self):
        (self.out / f"modules/lib/modules/{KVER}/modules.dep").unlink()
        self.assertError("depmod did not run")

    def test_config_value_not_applied(self):
        update_config(self.proj, lambda c: c["kernel"].update(config={"CONFIG_FOO": "m"}))
        self.assertError("CONFIG_FOO is not set to m")

    def test_config_n_satisfied_by_not_set(self):
        update_config(self.proj, lambda c: c["kernel"].update(config={"CONFIG_FOO": "n"}))
        (self.out / "config").write_text("# CONFIG_FOO is not set\n")
        self.assertEqual(self.restage_and_check(), [])

    def test_bad_kver(self):
        cfg = self.cfg()
        vk.write_metadata(self.out, cfg, "6.8.0-generic", "v", "a" * 40, "f" * 64)
        errs = vk.check(self.out, cfg, "xlnx,zynqmp", "xilinx")
        self.assertTrue(any("does not match" in e for e in errs), errs)

    def test_file_changed_after_staging(self):
        self.restage_and_check()
        (self.out / "config").write_text("CONFIG_ARCH_ZYNQMP=y\n# edited\n")
        errs = vk.check(self.out, self.cfg(), "xlnx,zynqmp", "xilinx")
        self.assertTrue(any("changed since kernel-build staged it" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
