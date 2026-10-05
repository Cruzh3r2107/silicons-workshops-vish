import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.fakekernel import make_fake_kernel_repo, make_patch
from tests.helpers import REPO, make_project, run, update_config

KVER = "6.8.0-1036-xilinx"


class KernelBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = make_fake_kernel_repo(self.tmp)
        self.proj = make_project(self.tmp, repository=str(self.repo))
        self.out = self.proj / "out/kernel"

    def build(self, **env):
        return run(["kernel-build"], self.proj, env)

    def builds(self):
        log = self.proj / "build/fake-rules.log"
        return log.read_text().split().count("build-xilinx") if log.exists() else 0

    def test_default_build_produces_validated_outputs(self):
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel in ("image/Image.gz", "dtbs/xilinx/board.dtb", "config",
                    f"modules/lib/modules/{KVER}/modules.dep", "metadata/build.json"):
            self.assertTrue((self.out / rel).is_file(), rel)
        meta = json.loads((self.out / "metadata/build.json").read_text())
        self.assertEqual(meta["kver"], KVER)
        self.assertEqual(meta["version"], "6.8.0-1036.37+workshop1")
        self.assertEqual(len(meta["commit"]), 40)
        self.assertIn("kernel-build complete", r.stdout)

    def test_staged_modules_are_stripped(self):
        # Ubuntu packages ship stripped modules; staging must match.
        self.assertEqual(self.build().returncode, 0)
        ko = self.out / f"modules/lib/modules/{KVER}/kernel/test.ko"
        self.assertFalse(ko.read_bytes().endswith(b"DEBUGINFO"))

    def test_second_run_reuses_outputs(self):
        self.assertEqual(self.build().returncode, 0)
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("up to date", r.stdout)
        self.assertEqual(self.builds(), 1)

    def test_sdk_code_change_triggers_rebuild(self):
        # Outputs built by older SDK code are not reused after an SDK update.
        (self.proj / ".workshop").unlink()
        shutil.copytree(REPO / ".workshop", self.proj / ".workshop")
        cmd = [str(self.proj / ".workshop/kernel/bin/kernel-build")]
        self.assertEqual(run(cmd, self.proj).returncode, 0)
        with open(self.proj / ".workshop/kernel/lib/kernel.sh", "a") as f:
            f.write("\n# sdk update\n")
        r = run(cmd, self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("up to date", r.stdout)
        self.assertEqual(self.builds(), 2)

    def test_config_change_triggers_rebuild(self):
        self.assertEqual(self.build().returncode, 0)
        update_config(self.proj, lambda c: c["kernel"].update(config={"CONFIG_FOO": "m"}))
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.builds(), 2)
        self.assertIn("CONFIG_FOO=m", (self.out / "config").read_text())

    def test_metadata_records_the_reuse_fingerprint(self):
        self.assertEqual(self.build().returncode, 0)
        meta = json.loads((self.out / "metadata/build.json").read_text())
        state = (self.proj / "build/state/kernel.fingerprint").read_text().strip()
        self.assertEqual(meta["fingerprint"], state)

    def test_patch_content_change_triggers_rebuild(self):
        make_patch(self.repo, self.proj / "patches/0001-add.patch")
        update_config(self.proj, lambda c: c.update(patches=["patches/0001-add.patch"]))
        self.assertEqual(self.build().returncode, 0)
        make_patch(self.repo, self.proj / "patches/0001-add.patch", filename="OTHER")
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.builds(), 2)
        self.assertTrue((self.proj / "build/linux/OTHER").is_file())

    def test_overlay_content_change_triggers_rebuild(self):
        dtso = self.proj / "overlays/extra.dtso"
        dtso.write_text("/dts-v1/;\n/plugin/;\n&{/} { extra { }; };\n")
        update_config(self.proj, lambda c: c.update(overlays=["overlays/extra.dtso"]))
        self.assertEqual(self.build().returncode, 0)
        dtso.write_text("/dts-v1/;\n/plugin/;\n&{/} { changed { }; };\n")
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.builds(), 2)

    def test_patch_is_applied(self):
        make_patch(self.repo, self.proj / "patches/0001-add.patch")
        update_config(self.proj, lambda c: c.update(patches=["patches/0001-add.patch"]))
        self.assertEqual(self.build().returncode, 0)
        self.assertTrue((self.proj / "build/linux/PATCHED").is_file())

    def test_bad_patch_fails_with_name_and_recovers(self):
        (self.proj / "patches/bad.patch").write_text("not a patch\n")
        update_config(self.proj, lambda c: c.update(patches=["patches/bad.patch"]))
        r = self.build()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('stage "prepare" failed', r.stderr)
        self.assertIn("patches/bad.patch does not apply", r.stderr)
        update_config(self.proj, lambda c: c.update(patches=[]))
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_overlay_is_built_and_staged(self):
        (self.proj / "overlays/extra.dtso").write_text("/dts-v1/;\n/plugin/;\n&{/} { extra { }; };\n")
        update_config(self.proj, lambda c: c.update(overlays=["overlays/extra.dtso"]))
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.out / "dtbs/xilinx/overlays/extra.dtbo").is_file())

    def test_missing_device_tree_fails(self):
        update_config(self.proj, lambda c: c["kernel"].update(
            device_trees=["xilinx/board.dtb", "xilinx/missing.dtb"]))
        r = self.build()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("requested device tree xilinx/missing.dtb was not built", r.stderr)

    def test_dtbs_checked_against_configured_compatible(self):
        update_config(self.proj, lambda c: c["silicon"].update(compatible="xlnx,versal"))
        r = self.build()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("root compatible does not include xlnx,versal", r.stderr)

    def test_branch_ref_rejected_before_clone(self):
        update_config(self.proj, lambda c: c["kernel"]["source"].update(ref="master-next"))
        r = self.build()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is a branch", r.stderr)
        self.assertFalse((self.proj / "build/linux").exists())

    def test_failed_build_is_not_reported_up_to_date(self):
        self.assertEqual(self.build().returncode, 0)
        update_config(self.proj, lambda c: c["kernel"].update(config={"CONFIG_FOO": "m"}))
        self.assertNotEqual(self.build(FAKE_FAIL_BUILD="1").returncode, 0)
        update_config(self.proj, lambda c: c["kernel"].update(config={}))
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("up to date", r.stdout)
        self.assertEqual(self.builds(), 3)

    def test_build_deps_are_resolved_for_the_build_machine(self):
        # Ubuntu's control lists arch-restricted deps that only apply to native
        # arm64 builds; a cross build must check deps for the build machine.
        r = self.build(FAKE_ARM64_ONLY_DEP="1")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_rejects_arguments(self):
        r = run(["kernel-build", "--fast"], self.proj)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("usage: kernel-build", r.stderr)

    def test_kernel_clean_removes_outputs_keeps_clone(self):
        self.assertEqual(self.build().returncode, 0)
        r = run(["kernel-clean"], self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.proj / "out").exists())
        self.assertFalse((self.proj / "build/state").exists())
        self.assertFalse((self.proj / "build/linux/debian/build").exists())
        self.assertTrue((self.proj / "build/linux/.git").is_dir())
        self.assertTrue((self.proj / "project.yaml").is_file())
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.builds(), 2)


if __name__ == "__main__":
    unittest.main()
