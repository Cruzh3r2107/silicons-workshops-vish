# shellcheck shell=sh
# Kernel SDK stages. Requires common.sh, ubuntu-kernel.sh and SDK_DIR.

GIT_IDENT="-c user.name=workshop -c user.email=workshop@localhost"

kb_load_config() {
	REPO=$(wscfg get kernel.source.repository)
	REF=$(wscfg get kernel.source.ref)
	FLAVOUR=$(wscfg get kernel.flavour)
	uk_load_silicon
}

# kb_ref_spec: the only revision $REF may name: a full 40-character commit
# SHA, otherwise a tag. Branches and abbreviated SHAs never resolve.
kb_ref_spec() {
	if printf '%s\n' "$REF" | grep -Eqx '[0-9a-f]{40}'; then
		printf '%s^{commit}\n' "$REF"
	else
		printf 'refs/tags/%s^{commit}\n' "$REF"
	fi
}

# kb_resolve_ref: print the commit for $REF, or die.
kb_resolve_ref() {
	git -C "$LINUX_DIR" rev-parse -q --verify "$(kb_ref_spec)" ||
		die "kernel.source.ref '$REF' is not a tag or full commit SHA in $REPO (branches are not accepted)"
}

kb_acquire_source() {
	if [ ! -d "$LINUX_DIR/.git" ]; then
		rm -rf "$LINUX_DIR"
		mkdir -p "$BUILD_DIR"
		info "cloning $REPO (full clone; Launchpad does not support shallow clones)"
		git clone --no-checkout -- "$REPO" "$LINUX_DIR"
	else
		git -C "$LINUX_DIR" remote set-url origin "$REPO"
		if ! git -C "$LINUX_DIR" rev-parse -q --verify "$(kb_ref_spec)" >/dev/null; then
			git -C "$LINUX_DIR" fetch --tags origin
		fi
	fi
	kb_resolve_ref >/dev/null
}

kb_prepare_tree() {
	_kb_sha=$(kb_resolve_ref)
	cd "$LINUX_DIR"
	git am --abort >/dev/null 2>&1 || true
	git checkout -q --force --detach "$_kb_sha"
	git reset -q --hard
	git clean -q -fdx

	_kb_debian=$(uk_debian_dir)
	[ -n "$_kb_debian" ] || die "debian/debian.env does not name a packaging directory"
	grep -Eq "^flavours[[:space:]]*=.*([[:space:]]|=)$FLAVOUR([[:space:]]|\$)" "$_kb_debian/rules.d/$DEB_ARCH.mk" ||
		die "kernel.flavour '$FLAVOUR' is not built for $DEB_ARCH by $_kb_debian/rules.d/$DEB_ARCH.mk"

	for _kb_p in $(wscfg get patches); do
		# shellcheck disable=SC2086
		if ! git $GIT_IDENT am -q --3way "$PROJECT_DIR/$_kb_p"; then
			git am --abort >/dev/null 2>&1 || true
			die "patch $_kb_p does not apply to $REF"
		fi
	done

	_kb_dts="arch/$KARCH/boot/dts/$DTS_SUBDIR"
	if [ -n "$(wscfg get overlays)" ] && [ ! -f "$_kb_dts/Makefile" ]; then
		die "silicon.dts_dir '$DTS_SUBDIR': $_kb_dts/Makefile not found in the kernel tree"
	fi
	for _kb_o in $(wscfg get overlays); do
		_kb_name=$(basename "$_kb_o" .dtso)
		[ ! -e "$_kb_dts/$_kb_name.dtso" ] ||
			die "overlay $_kb_o: $_kb_name.dtso already exists in the kernel tree ($_kb_dts); rename it"
		cp "$PROJECT_DIR/$_kb_o" "$_kb_dts/$_kb_name.dtso"
		printf 'dtb-$(%s) += %s.dtbo\n' "$DTB_KCONFIG" "$_kb_name" >>"$_kb_dts/Makefile"
	done

	_kb_cfg=$(wscfg get kernel.config)
	while IFS='=' read -r _kb_key _kb_value; do
		[ -n "$_kb_key" ] || continue
		debian/scripts/misc/annotations -f "$_kb_debian/config/annotations" \
			--arch "$DEB_ARCH" --flavour "$FLAVOUR" --config "$_kb_key" --write "$_kb_value"
	done <<EOF
$_kb_cfg
EOF

	sed -i "1s/(\([^)]*\))/(\1$LOCAL_SUFFIX)/" "$_kb_debian/changelog"

	git add -A
	# shellcheck disable=SC2086
	git $GIT_IDENT commit -q -m "workshop: project inputs"
}

# kb_builddeps: ensure the build-deps for cross-building the kernel are
# installed. Needs debian/control, which `debian/rules clean` generates.
# Ubuntu's control does not mark build tools (gcc, python3, clang, rustc) as
# build-machine packages, so resolving it for arm64 asks for arm64 tools. A
# kernel-only cross build (do_tools=false) needs the deps for the build
# machine plus the cross compiler the tree names; no arm64 libraries.
kb_builddeps() {
	cd "$LINUX_DIR"
	_kb_cc=$(grep -o "gcc-[0-9]*-${CROSS%-}" debian/control | head -n 1)
	_kb_missing=
	dpkg-checkbuilddeps -B debian/control || _kb_missing=1
	if [ -n "$_kb_cc" ] &&
		! dpkg-query -W -f '${Status}' "$_kb_cc" 2>/dev/null | grep -q 'install ok installed'; then
		echo "missing cross compiler: $_kb_cc"
		_kb_missing=1
	fi
	[ -n "$_kb_missing" ] || return 0
	sudo -n true 2>/dev/null ||
		die "missing build dependencies (listed above); run: sudo apt-get build-dep --arch-only $LINUX_DIR${_kb_cc:+ && sudo apt-get install $_kb_cc}"
	sudo apt-get update
	sudo DEBIAN_FRONTEND=noninteractive apt-get build-dep -y --arch-only "$LINUX_DIR"
	if [ -n "$_kb_cc" ]; then
		sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$_kb_cc"
	fi
	dpkg-checkbuilddeps -B debian/control
}

kb_build() {
	uk_rules "build-$FLAVOUR"
}

kb_stage() {
	_kb_bdir="$LINUX_DIR/debian/build/build-$FLAVOUR"
	_kb_out="$OUT_DIR/kernel"
	_kb_kver=$(uk_kver "$FLAVOUR")
	rm -rf "$_kb_out"
	mkdir -p "$_kb_out/image" "$_kb_out/dtbs" "$_kb_out/modules"

	cp "$_kb_bdir/arch/$KARCH/boot/$KERNEL_IMAGE" "$_kb_out/image/$KERNEL_IMAGE"
	cp "$_kb_bdir/.config" "$_kb_out/config"

	for _kb_dtb in $(wscfg get kernel.device_trees); do
		[ -f "$_kb_bdir/arch/$KARCH/boot/dts/$_kb_dtb" ] ||
			die "requested device tree $_kb_dtb was not built"
		mkdir -p "$_kb_out/dtbs/$(dirname "$_kb_dtb")"
		cp "$_kb_bdir/arch/$KARCH/boot/dts/$_kb_dtb" "$_kb_out/dtbs/$_kb_dtb"
	done
	for _kb_o in $(wscfg get overlays); do
		_kb_name=$(basename "$_kb_o" .dtso)
		_kb_src="$_kb_bdir/arch/$KARCH/boot/dts/$DTS_SUBDIR/$_kb_name.dtbo"
		[ -f "$_kb_src" ] || die "overlay $_kb_o was not built"
		mkdir -p "$_kb_out/dtbs/$DTS_SUBDIR/overlays"
		cp "$_kb_src" "$_kb_out/dtbs/$DTS_SUBDIR/overlays/"
	done

	make -C "$LINUX_DIR" O="$_kb_bdir" ARCH="$KARCH" CROSS_COMPILE="$CROSS" \
		KERNELRELEASE="$_kb_kver" INSTALL_MOD_PATH="$_kb_out/modules" INSTALL_MOD_STRIP=1 modules_install

	python3 "$SDK_DIR/lib/validate_kernel.py" metadata --project "$PROJECT_DIR" \
		--out-dir "$_kb_out" --kver "$_kb_kver" --version "$(uk_version)" \
		--commit "$(kb_resolve_ref)" --fingerprint "$_kb_fp"
}

kb_validate() {
	python3 "$SDK_DIR/lib/validate_kernel.py" check --project "$PROJECT_DIR" \
		--out-dir "$OUT_DIR/kernel" --root-compatible "$ROOT_COMPATIBLE" --dts-subdir "$DTS_SUBDIR"
}

kernel_build_main() {
	[ $# -eq 0 ] || die "usage: kernel-build (configure the build in project.yaml)"
	wscfg validate || exit 1
	kb_load_config
	# Inputs plus the SDK code that turns them into outputs, so an SDK update
	# never reuses outputs built by older code.
	_kb_fp=$({ wscfg fingerprint; cat "$SDK_DIR"/bin/* "$SDK_DIR"/lib/*.sh "$SDK_DIR"/lib/*.py \
		"$COMMON_DIR"/*.sh "$COMMON_DIR"/*.py; } | sha256sum | cut -d' ' -f1)
	if state_matches kernel.fingerprint "$_kb_fp" && kb_validate >/dev/null 2>&1; then
		info "kernel outputs are up to date and valid: $OUT_DIR/kernel"
		return 0
	fi
	# Invalidate before building so an interrupted or failed run is never
	# mistaken for a valid one.
	state_clear kernel.fingerprint
	run_stage source kb_acquire_source
	run_stage prepare kb_prepare_tree
	run_stage clean uk_rules --fakeroot clean
	run_stage build-deps kb_builddeps
	run_stage build kb_build
	run_stage stage kb_stage
	run_stage validate kb_validate
	state_write kernel.fingerprint "$_kb_fp"
	info "kernel-build complete: $OUT_DIR/kernel"
}

kernel_clean_main() {
	[ $# -eq 0 ] || die "usage: kernel-clean"
	info "removing generated build state (keeping the kernel git clone and project inputs)"
	if [ -d "$LINUX_DIR/.git" ]; then
		git -C "$LINUX_DIR" am --abort >/dev/null 2>&1 || true
		git -C "$LINUX_DIR" reset -q --hard
		git -C "$LINUX_DIR" clean -q -fdx
	fi
	rm -rf "$OUT_DIR" "$BUILD_DIR/snap" "$LOG_DIR" "$STATE_DIR"
	rm -f "$BUILD_DIR"/*.deb "$BUILD_DIR"/*.ddeb "$BUILD_DIR"/*.buildinfo "$BUILD_DIR"/*.changes
}
