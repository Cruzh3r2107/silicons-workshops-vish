import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.fakekernel import TAG, make_fake_kernel_repo, make_patch
from tests.helpers import make_project, sdk_env, update_config

PRELUDE = ('. "$PROJECT_DIR/lib/common/common.sh"; '
           '. "$PROJECT_DIR/lib/common/ubuntu-kernel.sh"; '
           'SDK_DIR="$PROJECT_DIR/.workshop/kernel"; . "$SDK_DIR/lib/kernel.sh"; '
           'kb_load_config; ')


class KernelPrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = make_fake_kernel_repo(self.tmp)
        self.proj = make_project(self.tmp, repository=str(self.repo))
        self.linux = self.proj / "build/linux"

    def sh(self, script):
        return subprocess.run(["sh", "-eu", "-c", PRELUDE + script],
                              env=sdk_env(self.proj), capture_output=True, text=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.linux), *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_acquire_clones_and_resolves_tag(self):
        r = self.sh("kb_acquire_source; kb_resolve_ref")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], self.git("rev-parse", f"{TAG}^{{commit}}"))

    def test_unknown_tag_fails(self):
        update_config(self.proj, lambda c: c["kernel"]["source"].update(ref="Ubuntu-xilinx-9.9.9-1.1"))
        r = self.sh("kb_acquire_source")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is not a tag", r.stderr)

    def test_short_hex_ref_is_not_resolved_as_a_commit(self):
        # Only full 40-character SHAs are commits; anything else must be a tag.
        short = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--short=8", "HEAD"],
                               capture_output=True, text=True, check=True).stdout.strip()
        update_config(self.proj, lambda c: c["kernel"]["source"].update(ref=short))
        r = self.sh("kb_acquire_source")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is not a tag", r.stderr)

    def test_new_tag_is_fetched_even_if_a_branch_has_its_name(self):
        from tests.fakekernel import git
        git(self.repo, "branch", "Ubuntu-xilinx-6.8.0-1037.38")
        self.assertEqual(self.sh("kb_acquire_source").returncode, 0)
        (self.repo / "NEW").write_text("x")
        git(self.repo, "add", "NEW")
        git(self.repo, "commit", "-q", "-m", "new release")
        git(self.repo, "tag", "Ubuntu-xilinx-6.8.0-1037.38")
        update_config(self.proj, lambda c: c["kernel"]["source"].update(ref="Ubuntu-xilinx-6.8.0-1037.38"))
        r = self.sh("kb_acquire_source; kb_resolve_ref")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1],
                         subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                        capture_output=True, text=True, check=True).stdout.strip())

    def test_overlay_may_not_replace_an_in_tree_overlay(self):
        (self.proj / "overlays/carrier.dtso").write_text("/dts-v1/;\n/plugin/;\n")
        update_config(self.proj, lambda c: c.update(overlays=["overlays/carrier.dtso"]))
        r = self.sh("kb_acquire_source; kb_prepare_tree")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("carrier.dtso already exists in the kernel tree", r.stderr)

    def test_repository_change_updates_origin(self):
        self.assertEqual(self.sh("kb_acquire_source").returncode, 0)
        moved = self.tmp / "moved-linux"
        shutil.copytree(self.repo, moved)
        update_config(self.proj, lambda c: c["kernel"]["source"].update(repository=str(moved)))
        self.assertEqual(self.sh("kb_acquire_source").returncode, 0)
        self.assertEqual(self.git("remote", "get-url", "origin"), str(moved))

    def test_prepare_applies_inputs_and_commits(self):
        make_patch(self.repo, self.proj / "patches/0001-add.patch")
        (self.proj / "overlays/extra.dtso").write_text("/dts-v1/;\n/plugin/;\n&{/} { extra { }; };\n")
        update_config(self.proj, lambda c: (c.update(patches=["patches/0001-add.patch"],
                                                     overlays=["overlays/extra.dtso"]),
                                            c["kernel"].update(config={"CONFIG_FOO": "m"})))
        r = self.sh("kb_acquire_source; kb_prepare_tree")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.linux / "PATCHED").is_file())
        dts = self.linux / "arch/arm64/boot/dts/xilinx"
        self.assertTrue((dts / "extra.dtso").is_file())
        self.assertIn("dtb-$(CONFIG_ARCH_ZYNQMP) += extra.dtbo", (dts / "Makefile").read_text())
        self.assertIn("CONFIG_FOO m", (self.linux / "debian.xilinx/config/annotations").read_text())
        self.assertIn("(6.8.0-1036.37+workshop1)", (self.linux / "debian.xilinx/changelog").read_text())
        self.assertEqual(self.git("log", "-1", "--format=%s"), "workshop: project inputs")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_prepare_is_repeatable(self):
        self.assertEqual(self.sh("kb_acquire_source; kb_prepare_tree").returncode, 0)
        r = self.sh("kb_prepare_tree")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.linux / "debian.xilinx/changelog").read_text().count("+workshop1"), 1)

    def test_bad_patch_names_patch(self):
        (self.proj / "patches/bad.patch").write_text("not a patch\n")
        update_config(self.proj, lambda c: c.update(patches=["patches/bad.patch"]))
        r = self.sh("kb_acquire_source; kb_prepare_tree")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("patches/bad.patch does not apply", r.stderr)

    def test_unsupported_flavour(self):
        update_config(self.proj, lambda c: c["kernel"].update(flavour="generic"))
        r = self.sh("kb_acquire_source; kb_prepare_tree")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("flavour 'generic' is not built for arm64", r.stderr)


if __name__ == "__main__":
    unittest.main()
