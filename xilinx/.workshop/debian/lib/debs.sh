# shellcheck shell=sh
# Debian Packaging SDK stages. Requires common.sh, ubuntu-kernel.sh and SDK_DIR.

debs_package() {
	rm -f "$BUILD_DIR"/*.deb "$BUILD_DIR"/*.ddeb
	uk_rules --fakeroot "binary-$FLAVOUR"
}

debs_collect() {
	set -- "$BUILD_DIR"/*.deb
	[ -e "$1" ] || die "debian/rules binary-$FLAVOUR produced no .deb files"
	rm -rf "$OUT_DIR/deb"
	mkdir -p "$OUT_DIR/deb"
	mv "$@" "$OUT_DIR/deb/"
	rm -f "$BUILD_DIR"/*.ddeb
	python3 "$SDK_DIR/lib/validate_debs.py" metadata --deb-dir "$OUT_DIR/deb"
}

debs_validate() {
	python3 "$SDK_DIR/lib/validate_debs.py" check --project "$PROJECT_DIR" \
		--deb-dir "$OUT_DIR/deb" --kernel-dir "$OUT_DIR/kernel" --dts-subdir "$DTS_SUBDIR"
}

debs_main() {
	[ $# -eq 0 ] || die "usage: kernel-build-debs (configure the build in project.yaml)"
	wscfg validate || exit 1
	command -v kernel-build >/dev/null ||
		die "kernel-build not found: the Kernel SDK (project-kernel) must be installed in this workshop"
	# Reuses valid kernel outputs, rebuilds stale ones.
	kernel-build
	FLAVOUR=$(wscfg get kernel.flavour)
	# The validated kernel state plus this SDK's code (see kernel_build_main).
	_db_fp=$({ cat "$STATE_DIR/kernel.fingerprint" "$SDK_DIR"/bin/* "$SDK_DIR"/lib/*.sh \
		"$SDK_DIR"/lib/*.py; } | sha256sum | cut -d' ' -f1)
	if state_matches debs.fingerprint "$_db_fp" && debs_validate >/dev/null 2>&1; then
		info "Debian packages are up to date and valid: $OUT_DIR/deb"
		return 0
	fi
	state_clear debs.fingerprint
	run_stage package debs_package
	run_stage collect debs_collect
	run_stage validate-debs debs_validate
	state_write debs.fingerprint "$_db_fp"
	info "kernel-build-debs complete: $OUT_DIR/deb"
}
