"""A tiny stand-in for an Ubuntu kernel git tree, for fast hermetic SDK tests.

It implements only the interfaces the SDKs use: debian/debian.env, the
$DEBIAN changelog/rules.d/annotations, the annotations tool, debian/rules
clean/build-<flavour>/binary-<flavour>, the xilinx dts Makefile, and
`make O=... modules_install`.
"""
import os
import subprocess
from pathlib import Path

TAG = "Ubuntu-xilinx-6.8.0-1036.37"

CHANGELOG = """linux-xilinx (6.8.0-1036.37) noble; urgency=medium

  * Fake release for tests.

 -- Test User <test@example.com>  Mon, 01 Jan 2024 00:00:00 +0000
"""

BOARD_DTS = """/dts-v1/;
/ {
	compatible = "xlnx,zynqmp-smk-k26", "xlnx,zynqmp";
	#address-cells = <2>;
	#size-cells = <2>;
	model = "Fake K26";
};
"""

ANNOTATIONS_TOOL = """#!/usr/bin/env python3
import argparse
p = argparse.ArgumentParser()
for opt in ("-f", "--arch", "--flavour", "--config", "--write"):
    p.add_argument(opt)
a = p.parse_args()
with open(a.f, "a") as f:
    f.write(f"{a.config} {a.write}\\n")
"""

RULES = r'''#!/usr/bin/env python3
import gzip, os, re, shutil, subprocess, sys
from pathlib import Path

tree = Path(__file__).resolve().parents[1]
target = sys.argv[1]
with (tree.parent / "fake-rules.log").open("a") as log:
    log.write(target + "\n")

bdir = tree / "debian" / "build" / "build-xilinx"
dts = tree / "arch" / "arm64" / "boot" / "dts" / "xilinx"


def version():
    first = (tree / "debian" / "changelog").read_text().splitlines()[0]
    return re.search(r"\((.*?)\)", first).group(1)


def kver():
    upstream, revision = version().rsplit("-", 1)
    return f"{upstream}-{revision.split('.')[0]}-xilinx"


def deb(pkg, files):
    root = tree / "debian" / pkg
    shutil.rmtree(root, ignore_errors=True)
    (root / "DEBIAN").mkdir(parents=True)
    (root / "DEBIAN" / "control").write_text(
        f"Package: {pkg}\nVersion: {version()}\nArchitecture: arm64\n"
        "Maintainer: Test <test@example.com>\nDescription: fake\n")
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    subprocess.run(["dpkg-deb", "--root-owner-group", "-Zgzip", "--build", str(root),
                    str(tree.parent / f"{pkg}_{version()}_arm64.deb")],
                   check=True, stdout=subprocess.DEVNULL)


if target == "clean":
    shutil.rmtree(tree / "debian" / "build", ignore_errors=True)
    shutil.copy(tree / "debian.xilinx" / "changelog", tree / "debian" / "changelog")
    # FAKE_ARM64_ONLY_DEP mimics Ubuntu's control: a dependency restricted to
    # arm64 that must not be required when cross-building on amd64.
    deps = "Build-Depends: workshop-test-nonexistent-dep [arm64]\n" if os.environ.get("FAKE_ARM64_ONLY_DEP") else ""
    (tree / "debian" / "control").write_text(
        f"Source: linux-xilinx\n{deps}\nPackage: linux-image-fake\nArchitecture: arm64\nDescription: fake\n")
elif target == "build-xilinx":
    if os.environ.get("FAKE_FAIL_BUILD"):
        sys.exit("fake build failure")
    if os.environ.get("DEB_HOST_ARCH") != "arm64" or not os.environ.get("CROSS_COMPILE"):
        sys.exit("cross-build environment not exported")
    boot = bdir / "arch" / "arm64" / "boot"
    (boot / "dts" / "xilinx").mkdir(parents=True, exist_ok=True)
    header = bytearray(64)
    header[56:60] = b"ARM\x64"
    (boot / "Image.gz").write_bytes(gzip.compress(bytes(header) + b"\0" * 1024, mtime=0))
    lines = ["CONFIG_ARCH_ZYNQMP=y"]
    for line in (tree / "debian.xilinx" / "config" / "annotations").read_text().splitlines():
        if line.startswith("CONFIG_"):
            key, value = line.split(None, 1)
            lines.append(f"# {key} is not set" if value == "n" else f"{key}={value}")
    (bdir / ".config").write_text("\n".join(lines) + "\n")
    stamps = tree / "debian" / "stamps"
    stamps.mkdir(parents=True, exist_ok=True)
    (stamps / "stamp-build-xilinx").write_text("")
    for m in re.finditer(r"\+= (\S+)\.(dtbo?)$", (dts / "Makefile").read_text(), re.M):
        name, kind = m.groups()
        src = dts / (name + (".dts" if kind == "dtb" else ".dtso"))
        subprocess.run(["dtc", "-q", "-@", "-I", "dts", "-O", "dtb", "-o",
                        str(boot / "dts" / "xilinx" / f"{name}.{kind}"), str(src)], check=True)
elif target == "binary-xilinx":
    if not bdir.is_dir():
        sys.exit("binary-xilinx: kernel has not been built")
    if not (tree / "debian" / "stamps" / "stamp-build-xilinx").exists():
        # Like the real rules: a missing build stamp means binary-% recompiles,
        # and the new image is not byte-identical to the staged one.
        with (tree.parent / "fake-rules.log").open("a") as log:
            log.write("implicit-rebuild\n")
        image_path = bdir / "arch" / "arm64" / "boot" / "Image.gz"
        image_path.write_bytes(image_path.read_bytes() + b"rebuilt")
    k = kver()
    image = (bdir / "arch" / "arm64" / "boot" / "Image.gz").read_bytes()
    if os.environ.get("FAKE_CORRUPT_VMLINUZ"):
        image += b"diverged"
    files = {f"boot/vmlinuz-{k}": image}
    for f in sorted((bdir / "arch" / "arm64" / "boot" / "dts" / "xilinx").iterdir()):
        files[f"lib/firmware/{k}/device-tree/xilinx/{f.name}"] = f.read_bytes()
    deb(f"linux-image-{k}", files)
    elf = bytearray(64)
    elf[0:4] = b"\x7fELF"
    elf[18:20] = (183).to_bytes(2, "little")
    deb(f"linux-modules-{k}", {f"lib/modules/{k}/kernel/test.ko": bytes(elf)})
elif target == "__modules_install":
    dest = Path(sys.argv[2]) / "lib" / "modules" / sys.argv[3]
    (dest / "kernel").mkdir(parents=True, exist_ok=True)
    elf = bytearray(64)
    elf[0:4] = b"\x7fELF"
    elf[4], elf[5] = 2, 1
    elf[18:20] = (183).to_bytes(2, "little")
    # Unstripped modules keep debug info; mimic it with a trailing marker.
    debug = b"" if len(sys.argv) > 4 and sys.argv[4] else b"DEBUGINFO"
    (dest / "kernel" / "test.ko").write_bytes(bytes(elf) + debug)
    (dest / "modules.dep").write_text("kernel/test.ko:\n")
else:
    sys.exit(f"fake debian/rules: unknown target {target}")
'''

TOP_MAKEFILE = ('modules_install:\n'
                '\tpython3 debian/rules __modules_install "$(INSTALL_MOD_PATH)" "$(KERNELRELEASE)" "$(INSTALL_MOD_STRIP)"\n')

GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})


def make_fake_kernel_repo(root):
    repo = Path(root) / "fake-linux"
    files = {
        "debian/debian.env": "DEBIAN=debian.xilinx\n",
        "debian/rules": RULES,
        "debian/scripts/misc/annotations": ANNOTATIONS_TOOL,
        "debian.xilinx/changelog": CHANGELOG,
        "debian.xilinx/rules.d/arm64.mk": "flavours\t= xilinx\n",
        "debian.xilinx/config/annotations": "# Menu: fake\n",
        "arch/arm64/boot/dts/xilinx/Makefile": "dtb-$(CONFIG_ARCH_ZYNQMP) += board.dtb\n",
        "arch/arm64/boot/dts/xilinx/board.dts": BOARD_DTS,
        "Makefile": TOP_MAKEFILE,
    }
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (repo / "debian/rules").chmod(0o755)
    (repo / "debian/scripts/misc/annotations").chmod(0o755)
    subprocess.run(["git", "init", "-q", "-b", "master-next", str(repo)], check=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fake kernel")
    git(repo, "tag", TAG)
    return repo


def make_patch(repo, dest, filename="PATCHED"):
    work = Path(dest).parent / f"patch-work-{filename}"
    subprocess.run(["git", "clone", "-q", str(repo), str(work)], check=True)
    (work / filename).write_text("yes\n")
    git(work, "add", filename)
    git(work, "commit", "-q", "-m", f"test: add {filename}")
    out = subprocess.run(["git", "-C", str(work), "format-patch", "-1", "--stdout"],
                         check=True, capture_output=True, text=True).stdout
    Path(dest).write_text(out)
