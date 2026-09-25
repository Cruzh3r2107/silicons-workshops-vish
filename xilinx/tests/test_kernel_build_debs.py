import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.fakekernel import make_fake_kernel_repo
from tests.helpers import REPO, make_project, run

KVER = "6.8.0-1036-xilinx"
VERSION = "6.8.0-1036.37+workshop1"


class KernelBuildDebsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = make_fake_kernel_repo(self.tmp)
        self.proj = make_project(self.tmp, repository=str(self.repo))
        self.debs = self.proj / "out/deb"

    def targets(self):
        return (self.proj / "build/fake-rules.log").read_text().split()

    def test_debs_built_and_validated(self):
        r = run(["kernel-build-debs"], self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        for pkg in (f"linux-image-{KVER}", f"linux-modules-{KVER}"):
            self.assertTrue((self.debs / f"{pkg}_{VERSION}_arm64.deb").is_file(), pkg)
        meta = json.loads((self.debs / "metadata/packages.json").read_text())
        self.assertEqual({m["package"] for m in meta},
                         {f"linux-image-{KVER}", f"linux-modules-{KVER}", f"linux-headers-{KVER}"})
        self.assertEqual(self.targets().count("build-xilinx"), 1)
        self.assertEqual(self.targets().count("binary-xilinx"), 1)
        self.assertIn("kernel-build-debs complete", r.stdout)

    def test_second_run_up_to_date(self):
        self.assertEqual(run(["kernel-build-debs"], self.proj).returncode, 0)
        r = run(["kernel-build-debs"], self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("up to date", r.stdout)
        self.assertEqual(self.targets().count("binary-xilinx"), 1)

    def test_deleted_optional_package_is_rebuilt(self):
        # packages.json records every built package; out/deb must still match it.
        self.assertEqual(run(["kernel-build-debs"], self.proj).returncode, 0)
        (self.debs / f"linux-headers-{KVER}_{VERSION}_arm64.deb").unlink()
        r = run(["kernel-build-debs"], self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Debian packages are up to date", r.stdout)
        self.assertTrue((self.debs / f"linux-headers-{KVER}_{VERSION}_arm64.deb").is_file())

    def test_diverged_vmlinuz_fails(self):
        r = run(["kernel-build-debs"], self.proj, {"FAKE_CORRUPT_VMLINUZ": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("differs from", r.stderr)

    def test_missing_build_stamp_rebuilds_kernel_first(self):
        # With the build stamp gone, binary-xilinx would recompile and diverge
        # from out/kernel; kernel-build-debs must rebuild the kernel instead.
        self.assertEqual(run(["kernel-build"], self.proj).returncode, 0)
        (self.proj / "build/linux/debian/stamps/stamp-build-xilinx").unlink()
        r = run(["kernel-build-debs"], self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.targets().count("build-xilinx"), 2)
        self.assertNotIn("implicit-rebuild", self.targets())

    def test_missing_deb_dir_contents_rebuilt(self):
        self.assertEqual(run(["kernel-build-debs"], self.proj).returncode, 0)
        for deb in self.debs.glob("*.deb"):
            deb.unlink()
        r = run(["kernel-build-debs"], self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.targets().count("binary-xilinx"), 2)

    def test_sdk_code_change_triggers_repackaging(self):
        (self.proj / ".workshop").unlink()
        shutil.copytree(REPO / ".workshop", self.proj / ".workshop")
        cmd = [str(self.proj / ".workshop/debian/bin/kernel-build-debs")]
        self.assertEqual(run(cmd, self.proj).returncode, 0)
        with open(self.proj / ".workshop/debian/lib/debs.sh", "a") as f:
            f.write("\n# sdk update\n")
        r = run(cmd, self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.targets().count("binary-xilinx"), 2)


if __name__ == "__main__":
    unittest.main()
