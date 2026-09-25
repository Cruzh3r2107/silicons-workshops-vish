# shellcheck shell=sh
# Snap Packaging SDK stages. Requires common.sh, ubuntu-kernel.sh and SDK_DIR.

SNAP_DIR="$BUILD_DIR/snap"
ARCHIVE_DIR="$SNAP_DIR/archive"
SNAP_PROJECT="$SNAP_DIR/project"
APT_SOURCE=/etc/apt/sources.list.d/workshop-local.sources
APT_PIN=/etc/apt/preferences.d/workshop-local

# snap_check_host: the initrd plugin runs arm64 binaries in a chroot. Prove
# they execute here (host qemu-user-static binfmt with the F flag) by running
# a tiny static aarch64 program; /proc/sys/fs/binfmt_misc is often not
# mounted inside containers even when the host handler works.
snap_check_host() {
	_sn_probe=${AARCH64_PROBE:-}
	if [ -z "$_sn_probe" ]; then
		mkdir -p "$SNAP_DIR"
		_sn_probe="$SNAP_DIR/aarch64-probe"
		printf 'int main(void) { return 0; }\n' |
			"${CROSS}gcc" -static -x c -o "$_sn_probe" - ||
			die "cannot build the aarch64 probe with ${CROSS}gcc (Kernel SDK toolchain missing?)"
	fi
	"$_sn_probe" 2>/dev/null ||
		die "arm64 binaries cannot run in this Workshop: install qemu-user-static on the host (binfmt_misc qemu-aarch64 with the F flag), then relaunch the Workshop"
}

snap_archive() {
	rm -rf "$ARCHIVE_DIR"
	mkdir -p "$ARCHIVE_DIR"
	cp "$OUT_DIR"/deb/*.deb "$ARCHIVE_DIR/"
	(cd "$ARCHIVE_DIR" && apt-ftparchive packages . >Packages)
}

# The local apt source and pin exist only while snapcraft runs, so deleting
# build/snap (kernel-clean) never leaves apt pointing at a missing archive.
snap_publish_archive() {
	printf 'Types: deb\nURIs: file:%s\nSuites: ./\nTrusted: yes\n' "$ARCHIVE_DIR" |
		sudo tee "$APT_SOURCE" >/dev/null
	printf 'Package: *\nPin: origin ""\nPin-Priority: 1001\n' | sudo tee "$APT_PIN" >/dev/null
	sudo apt-get update
}

snap_unpublish_archive() {
	sudo rm -f "$APT_SOURCE" "$APT_PIN"
}

snap_render() {
	rm -rf "$SNAP_PROJECT"
	python3 "$SDK_DIR/lib/render_snap.py" --project "$PROJECT_DIR" --kernel-dir "$OUT_DIR/kernel" \
		--template "$SDK_DIR/snapcraft.yaml.in" --out-dir "$SNAP_PROJECT"
}

# Destructive mode builds in this (disposable) Workshop, whose base matches
# core24, and installs build packages with apt, so it runs as root.
snap_pack() {
	trap snap_unpublish_archive EXIT
	snap_publish_archive
	cd "$SNAP_PROJECT"
	sudo snapcraft pack --destructive-mode --build-for="$DEB_ARCH"
	sudo chown -R "$(id -u):$(id -g)" "$SNAP_PROJECT"
}

snap_collect() {
	set -- "$SNAP_PROJECT"/*.snap
	[ -e "$1" ] || die "snapcraft produced no .snap file"
	rm -rf "$OUT_DIR/snap"
	mkdir -p "$OUT_DIR/snap"
	mv "$1" "$OUT_DIR/snap/"
	python3 "$SDK_DIR/lib/validate_snap.py" metadata --snap "$OUT_DIR/snap/$(basename "$1")" \
		--kernel-dir "$OUT_DIR/kernel"
}

snap_validate() {
	set -- "$OUT_DIR"/snap/*.snap
	[ -e "$1" ] || die "no snap in $OUT_DIR/snap"
	python3 "$SDK_DIR/lib/validate_snap.py" check --project "$PROJECT_DIR" --snap "$1" \
		--kernel-dir "$OUT_DIR/kernel" --dts-subdir "$DTS_SUBDIR"
}

snap_main() {
	[ $# -eq 0 ] || die "usage: kernel-build-snap (configure the build in project.yaml)"
	wscfg validate || exit 1
	command -v kernel-build-debs >/dev/null ||
		die "kernel-build-debs not found: the Debian Packaging SDK (project-debian) must be installed in this workshop"
	command -v snapcraft >/dev/null || die "snapcraft not found: the Snap SDK setup did not complete"
	sudo -n true 2>/dev/null ||
		die "kernel-build-snap needs passwordless sudo in the Workshop (local apt source, snapcraft --destructive-mode)"
	# A previous run killed mid-pack may have left the local source behind.
	snap_unpublish_archive
	snap_check_host
	# Reuses valid debs (and kernel outputs), rebuilds stale ones.
	kernel-build-debs
	# Render first: it is cheap, and hashing the rendered project makes
	# silicon.board / ubuntu.release changes invalidate the snap.
	run_stage render snap_render
	_sn_fp=$({ cat "$STATE_DIR/debs.fingerprint" "$SNAP_PROJECT/snapcraft.yaml" \
		"$SNAP_PROJECT/kernel.yaml" "$SDK_DIR"/bin/* "$SDK_DIR"/lib/*.sh "$SDK_DIR"/lib/*.py; } |
		sha256sum | cut -d' ' -f1)
	if state_matches snap.fingerprint "$_sn_fp" && snap_validate >/dev/null 2>&1; then
		info "kernel snap is up to date and valid: $OUT_DIR/snap"
		return 0
	fi
	state_clear snap.fingerprint
	run_stage archive snap_archive
	run_stage snapcraft snap_pack
	run_stage collect-snap snap_collect
	run_stage validate-snap snap_validate
	state_write snap.fingerprint "$_sn_fp"
	info "kernel-build-snap complete: $OUT_DIR/snap"
}
