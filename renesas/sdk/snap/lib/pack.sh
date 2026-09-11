#!/usr/bin/bash
# sdk/snap/lib/pack.sh — Ubuntu Core kernel snap build (from source).
#
# Builds the kernel snap with `snapcraft pack` against the snapcraft.yaml
# shipped in the kernel repository, matching the established Renesas flow. The
# snap is built directly from source (see DESIGN.md § Divergences for the
# rationale and the contract's alternative deb→plugin:kernel path).

[[ -n "${_SNAP_PACK_SH:-}" ]] && return 0
_SNAP_PACK_SH=1

# snap_locate_project ROOT — echoes the dir containing snap/snapcraft.yaml.
snap_locate_project() {
    local root="${1}"
    local src="${root}/kernel-src"
    if   [[ -f "${src}/snap/snapcraft.yaml" ]]; then echo "${src}"
    elif [[ -f "${src}/snapcraft.yaml"       ]]; then echo "${src}"
    else return 1
    fi
}

# snap_build ROOT ARCH — runs snapcraft pack in the kernel source tree.
snap_build() {
    local root="${1}" arch="${2}"
    local proj
    proj="$(snap_locate_project "${root}")" || workshop_fail \
        "No snapcraft.yaml found in kernel-src (expected snap/snapcraft.yaml shipped by the kernel repo)."

    workshop_register_binfmt "${arch}"

    workshop_log "Building kernel snap from source for ${arch} via snapcraft..."
    (
        cd "${proj}"
        # snapcraft runs as root; --preserve-env forwards ssh-agent for
        # git+ssh:// part sources (private repos authenticate this way).
        sudo --preserve-env=SSH_AUTH_SOCK \
            snapcraft pack --destructive-mode --build-for="${arch}" ${SNAPCRAFT_OPTS:-} >&2 \
            || workshop_fail "snapcraft pack failed"
    )
    return 0
}

# snap_stage ROOT — collect produced .snap into out/snap/.
snap_stage() {
    local root="${1}"
    local proj
    proj="$(snap_locate_project "${root}")" || workshop_fail "kernel snap project not found for staging"
    local out="${root}/out/snap"

    # out/snap is a normal project dir; clear its contents for a fresh stage.
    mkdir -p "${out}/metadata"
    rm -rf "${out:?}"/* 2>/dev/null || true
    mkdir -p "${out}/metadata"

    local count=0 f
    shopt -s nullglob
    for f in "${proj}"/*.snap; do
        mv -f "${f}" "${out}/"
        count=$((count+1))
    done
    shopt -u nullglob

    [[ "${count}" -gt 0 ]] || workshop_fail "No .snap file was produced."
    workshop_log "Staged ${count} snap(s) → out/snap/"
    ( cd "${out}" && ls -1 *.snap ) > "${out}/metadata/snaps.txt"
    return 0
}
