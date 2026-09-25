import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_project, sdk_env

PRELUDE = ('. "$PROJECT_DIR/lib/common/common.sh"; . "$PROJECT_DIR/lib/common/ubuntu-kernel.sh"; '
           'SDK_DIR="$PROJECT_DIR/.workshop/snap"; . "$SDK_DIR/lib/snap.sh"; ')


class SnapHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = make_project(self.tmp)

    def check(self, extra=None):
        return subprocess.run(["sh", "-eu", "-c", PRELUDE + "snap_check_host"],
                              env=sdk_env(self.proj, extra), capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("aarch64-linux-gnu-gcc")
                         and Path("/proc/sys/fs/binfmt_misc/qemu-aarch64").exists(),
                         "needs the arm64 cross compiler and a host aarch64 binfmt handler")
    def test_runnable_probe_passes_and_is_built_once(self):
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)
        probe = self.proj / "build/snap/aarch64-probe"
        first = probe.stat().st_mtime_ns
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(probe.stat().st_mtime_ns, first)

    def test_unrunnable_probe_fails_with_fix(self):
        probe = self.tmp / "probe"
        probe.write_bytes(b"\x7fELF" + b"\0" * 60)   # not runnable anywhere
        probe.chmod(0o755)
        r = self.check({"AARCH64_PROBE": str(probe)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("qemu-user-static", r.stderr)


if __name__ == "__main__":
    unittest.main()
