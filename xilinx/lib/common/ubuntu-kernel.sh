# shellcheck shell=sh
# Silicon constants for this Workshop (AMD/Xilinx ZynqMP, arm64) and helpers
# for driving an Ubuntu kernel git tree. Requires common.sh.

KARCH=arm64
DEB_ARCH=arm64
CROSS=aarch64-linux-gnu-
DTS_SUBDIR=xilinx
DTB_KCONFIG=CONFIG_ARCH_ZYNQMP
ROOT_COMPATIBLE=xlnx,zynqmp
KERNEL_IMAGE=Image.gz
LOCAL_SUFFIX=+workshop1
# ABI/module/retpoline checks compare against the archive's previous upload,
# which local changes legitimately diverge from; tools are not delivered.
UK_RULES_ARGS="do_skip_checks=true do_tools=false"

# uk_debian_dir: the tree's packaging directory (e.g. debian.xilinx).
uk_debian_dir() {
	sed -n 's/^DEBIAN=//p' "$LINUX_DIR/debian/debian.env"
}

# uk_version: package version from the top changelog entry.
uk_version() {
	dpkg-parsechangelog -l "$LINUX_DIR/$(uk_debian_dir)/changelog" -S Version
}

# uk_kver FLAVOUR: kernel release, e.g. 6.8.0-1036-xilinx (mirrors abinum in
# debian/rules.d/0-common-vars.mk).
uk_kver() {
	_uk_v=$(uk_version)
	_uk_rev=${_uk_v##*-}
	printf '%s-%s-%s\n' "${_uk_v%-*}" "${_uk_rev%%.*}" "$1"
}

# uk_rules [--fakeroot] TARGET: run debian/rules TARGET in the arm64
# cross-build environment.
uk_rules() {
	_uk_fr=
	if [ "$1" = --fakeroot ]; then
		_uk_fr=fakeroot
		shift
	fi
	(
		cd "$LINUX_DIR"
		eval "$(dpkg-architecture -a"$DEB_ARCH" -s 2>/dev/null)"
		export CROSS_COMPILE="$CROSS"
		# shellcheck disable=SC2086
		$_uk_fr debian/rules "$1" $UK_RULES_ARGS
	)
}
