# shellcheck shell=sh
# Kernel SDK stages. Requires common.sh, ubuntu-kernel.sh and SDK_DIR.

GIT_IDENT="-c user.name=workshop -c user.email=workshop@localhost"

kb_load_config() {
	REPO=$(wscfg get kernel.source.repository)
	REF=$(wscfg get kernel.source.ref)
	FLAVOUR=$(wscfg get kernel.flavour)
}

# kb_resolve_ref: print the commit for $REF. Tags are resolved only under
# refs/tags so that branch names can never be used.
kb_resolve_ref() {
	case "$REF" in
	*[!0-9a-f]*)
		git -C "$LINUX_DIR" rev-parse -q --verify "refs/tags/$REF^{commit}" ||
			die "kernel.source.ref '$REF' is not a tag in $REPO (branches are not accepted)"
		;;
	*)
		git -C "$LINUX_DIR" rev-parse -q --verify "$REF^{commit}" ||
			die "kernel.source.ref commit $REF not found in $REPO"
		;;
	esac
}

kb_acquire_source() {
	if [ ! -d "$LINUX_DIR/.git" ]; then
		rm -rf "$LINUX_DIR"
		mkdir -p "$BUILD_DIR"
		info "cloning $REPO (full clone; Launchpad does not support shallow clones)"
		git clone --no-checkout "$REPO" "$LINUX_DIR"
	else
		git -C "$LINUX_DIR" remote set-url origin "$REPO"
		if ! git -C "$LINUX_DIR" rev-parse -q --verify "$REF^{commit}" >/dev/null; then
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
	for _kb_o in $(wscfg get overlays); do
		_kb_name=$(basename "$_kb_o" .dtso)
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
