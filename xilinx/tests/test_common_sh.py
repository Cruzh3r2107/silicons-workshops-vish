import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_project, sdk_env

PRELUDE = '. "$PROJECT_DIR/lib/common/common.sh"; . "$PROJECT_DIR/lib/common/ubuntu-kernel.sh"; '

CHANGELOG = """linux-xilinx (6.8.0-1036.37+workshop1) noble; urgency=medium

  * Test.

 -- Test User <test@example.com>  Mon, 01 Jan 2024 00:00:00 +0000
"""


class CommonShTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = make_project(self.tmp)

    def sh(self, script):
        return subprocess.run(["sh", "-eu", "-c", PRELUDE + script],
                              env=sdk_env(self.proj), capture_output=True, text=True)

    def test_run_stage_success_writes_log(self):
        r = self.sh('f() { echo hello; }; run_stage greet f')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("==> greet", r.stdout)
        self.assertEqual((self.proj / "build/logs/greet.log").read_text(), "hello\n")

    def test_run_stage_failure_reports_stage_and_log(self):
        r = self.sh('f() { echo detail; exit 3; }; run_stage boom f; echo unreachable')
        self.assertEqual(r.returncode, 1)
        self.assertIn('stage "boom" failed', r.stderr)
        self.assertIn("detail", r.stderr)
        self.assertNotIn("unreachable", r.stdout)

    def test_run_stage_applies_errexit_inside_functions(self):
        r = self.sh('f() { false; echo after; }; run_stage strict f')
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("after", (self.proj / "build/logs/strict.log").read_text())

    def test_state_helpers(self):
        r = self.sh('state_write k abc; state_matches k abc && echo yes; '
                    'state_matches k other || echo no; state_clear k; state_matches k abc || echo gone')
        self.assertEqual(r.stdout.split(), ["yes", "no", "gone"])

    def test_wscfg_reads_project(self):
        self.assertEqual(self.sh("wscfg get kernel.flavour").stdout, "xilinx\n")

    def test_uk_version_and_kver(self):
        linux = self.proj / "build/linux"
        (linux / "debian").mkdir(parents=True)
        (linux / "debian.xilinx").mkdir()
        (linux / "debian/debian.env").write_text("DEBIAN=debian.xilinx\n")
        (linux / "debian.xilinx/changelog").write_text(CHANGELOG)
        r = self.sh("uk_debian_dir; uk_version; uk_kver xilinx")
        self.assertEqual(r.stdout.split(), ["debian.xilinx", "6.8.0-1036.37+workshop1", "6.8.0-1036-xilinx"])


if __name__ == "__main__":
    unittest.main()
