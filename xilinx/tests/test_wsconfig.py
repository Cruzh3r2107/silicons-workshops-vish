import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, host_release, make_project, update_config

sys.path.insert(0, str(REPO / "lib" / "common"))
import wsconfig  # noqa: E402

CLI = [sys.executable, str(REPO / "lib" / "common" / "wsconfig.py")]


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = make_project(self.tmp)

    def errors(self):
        cfg = wsconfig.load(self.proj)
        return wsconfig.validate(cfg, self.proj, host_release())

    def assertError(self, fragment):
        errs = self.errors()
        self.assertTrue(any(fragment in e for e in errs), f"{fragment!r} not in {errs}")

    def test_default_is_valid(self):
        self.assertEqual(self.errors(), [])

    def test_checked_in_project_yaml_is_valid(self):
        cfg = wsconfig.load(REPO)
        self.assertEqual(wsconfig.validate(cfg, REPO, "noble"), [])
        self.assertEqual(cfg["kernel"]["source"]["ref"], "Ubuntu-xilinx-6.8.0-1036.37")
        self.assertEqual(cfg["kernel"]["device_trees"], [
            "xilinx/zynqmp-smk-k26-revA-sck-kv-g-revA.dtb",
            "xilinx/zynqmp-smk-k26-revA-sck-kv-g-revB.dtb",
        ])

    def test_unknown_key(self):
        update_config(self.proj, lambda c: c.update(extra=1))
        self.assertError("extra: unknown key")

    def test_missing_key(self):
        update_config(self.proj, lambda c: c["kernel"].pop("flavour"))
        self.assertError("kernel.flavour: required key missing")

    def test_branch_ref_rejected(self):
        update_config(self.proj, lambda c: c["kernel"]["source"].update(ref="master-next"))
        self.assertError("is a branch")

    def test_sha_ref_accepted(self):
        update_config(self.proj, lambda c: c["kernel"]["source"].update(ref="a" * 40))
        self.assertEqual(self.errors(), [])

    def test_yaml_boolean_config_value_rejected(self):
        (self.proj / "project.yaml").write_text(
            (self.proj / "project.yaml").read_text().replace("config: {}", "config: {CONFIG_FOO: yes}"))
        self.assertError("quote the value")

    def test_yaml_coerced_numbers_rejected(self):
        # PyYAML (YAML 1.1) turns 0x10 into 16, 010 into 8 and 1:30 into 90,
        # which would silently misconfigure the kernel.
        for raw in ("0x10", "010", "1:30"):
            with self.subTest(raw=raw):
                (self.proj / "project.yaml").write_text(
                    (self.proj / "project.yaml").read_text().replace("config: {}", f"config: {{CONFIG_FOO: {raw}}}"))
                self.assertError("quote the value")
                update_config(self.proj, lambda c: c["kernel"].update(config={}))

    def test_bad_config_key(self):
        update_config(self.proj, lambda c: c["kernel"].update(config={"FOO": "y"}))
        self.assertError("must look like CONFIG_NAME")

    def test_missing_patch_file(self):
        update_config(self.proj, lambda c: c.update(patches=["patches/nope.patch"]))
        self.assertError("'patches/nope.patch' does not exist")

    def test_patch_outside_patches_dir(self):
        (self.proj / "evil.patch").write_text("x")
        update_config(self.proj, lambda c: c.update(patches=["evil.patch"]))
        self.assertError("must be a relative path under patches/")

    def test_whitespace_in_path_rejected(self):
        (self.proj / "patches" / "a b.patch").write_text("x")
        update_config(self.proj, lambda c: c.update(patches=["patches/a b.patch"]))
        self.assertError("without spaces")

    def test_overlay_must_be_dtso(self):
        (self.proj / "overlays" / "x.dts").write_text("x")
        update_config(self.proj, lambda c: c.update(overlays=["overlays/x.dts"]))
        self.assertError("must end in .dtso")

    def test_duplicate_dtb(self):
        update_config(self.proj, lambda c: c["kernel"].update(
            device_trees=["xilinx/board.dtb", "xilinx/board.dtb"]))
        self.assertError("listed twice")

    def test_release_mismatch(self):
        cfg = wsconfig.load(self.proj)
        errs = wsconfig.validate(cfg, self.proj, "some-other-release")
        self.assertTrue(any("ubuntu.release" in e for e in errs), errs)

    def test_invalid_yaml(self):
        (self.proj / "project.yaml").write_text("kernel: [unclosed\n")
        with self.assertRaises(wsconfig.ConfigError):
            wsconfig.load(self.proj)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = make_project(self.tmp)

    def cli(self, *args):
        return subprocess.run(CLI + ["--project", str(self.proj), *args],
                              capture_output=True, text=True)

    def test_get_scalar(self):
        self.assertEqual(self.cli("get", "kernel.flavour").stdout, "xilinx\n")

    def test_get_list(self):
        update_config(self.proj, lambda c: c["kernel"].update(
            device_trees=["xilinx/a.dtb", "xilinx/b.dtb"]))
        self.assertEqual(self.cli("get", "kernel.device_trees").stdout, "xilinx/a.dtb\nxilinx/b.dtb\n")

    def test_get_map_and_empty(self):
        update_config(self.proj, lambda c: c["kernel"].update(config={"CONFIG_A": "m", "CONFIG_HZ": "250"}))
        self.assertEqual(self.cli("get", "kernel.config").stdout, "CONFIG_A=m\nCONFIG_HZ=250\n")
        self.assertEqual(self.cli("get", "patches").stdout, "")

    def test_validate_failure_exit_code_and_message(self):
        update_config(self.proj, lambda c: c.update(extra=1))
        r = self.cli("validate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("project.yaml: extra: unknown key", r.stderr)

    def test_fingerprint_changes_with_patch_content(self):
        (self.proj / "patches" / "p.patch").write_text("one")
        update_config(self.proj, lambda c: c.update(patches=["patches/p.patch"]))
        first = self.cli("fingerprint").stdout
        (self.proj / "patches" / "p.patch").write_text("two")
        self.assertNotEqual(first, self.cli("fingerprint").stdout)


if __name__ == "__main__":
    unittest.main()
