# Renesas Silicon Workshop

A reproducible build environment for the **Renesas Ubuntu Kernel** for reference EVKs. It produces:

- **Ubuntu kernel Debian packages** (`.deb`) — for Ubuntu Classic
- **Ubuntu Core kernel snap** (`.snap`) — for Ubuntu Core
- **Gadget snap** (extra convenience for boot assets)

The kernel `.deb` and the kernel `.snap` are built directly from the configured
kernel source. What gets built is controlled declaratively in
`config/workshop.yaml`; how it is built lives in the SDKs under `sdk/`.

---

## 1. Prerequisites

- The **`workshop`** tool (Canonical craft-family orchestration).
- Network access to the configured kernel repository. The checked-in defaults
  use **public** Launchpad repos (`https://`, no auth needed).
- Only if a repo is **private** (`git+ssh://…`): load your key into ssh-agent
  (`ssh-add -l` to verify) and connect the ssh-agent plug (see §3). For a
  private Launchpad host that needs an explicit user, add it to your **own**
  `~/.ssh/config` outside the workshop — never to project config.

The build host (cross-toolchains, snapcraft, rust, qemu binfmt, kernel
build-deps) is provisioned automatically by the workshop's setup hooks — you do
not install those yourself.

---

## 2. Configure what to build

`config/workshop.yaml` is the single declarative configuration. The checked-in
defaults describe the reference RZ/T2H EVK and work as-is. Adjust if needed:

```yaml
silicon:
  soc: rzt2h            # rzt2h | rzn2h (used by gadget)
  board: rzt2h-evk      # not needed
ubuntu:
  release: resolute     # must match the workshop variant you launch (see §3)
  core_base: core26     # core24 | core26  (gadget/snap base folder)
kernel:
  # Public https:// example (resolute). Noble:
  #   https://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-renesas/+git/noble
  repository: https://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-renesas/+git/resolute
  ref:
    type: branch        # branch | tag | commit
    value: main-next
  config:
    type: flavour
    value: renesas      # debian/scripts/misc/annotations --flavour
  device_trees: []      # empty = stage all produced DTBs
toolchain:
  arch: arm64           # arm64 (Cortex-A55) | armhf (Cortex-R52)
  cross_compile: ""     # empty = auto-derive from arch
```

---

## 3. Launch the workshop

Two base variants. **Launch the one matching `ubuntu.release`:**

| Variant | Ubuntu base | Set `ubuntu.release` to |
|---------|-------------|-------------------------|
| `renesas-resolute` | 26.04 | `resolute` |
| `renesas-noble`    | 24.04 | `noble` |

```
workshop launch renesas-resolute
```

The first launch runs provisioning (`setup-base`, `setup-project`, health
check) — installs toolchains/build-deps and may take several minutes.

Only if you use a **private** repo, connect ssh-agent (plug lives on each SDK):

```
workshop connect renesas-resolute/deb-sdk:ssh-agent
```

---

## 4. Commands

Run with `workshop run <WORKSHOP> -- <command>`. **Clone once, then build
repeatedly.** Cloning is a separate step; the build commands never clone or
fetch — they use the already-cloned `kernel-src/` as-is.

> **Always name the workshop** (`renesas-resolute` or `renesas-noble`). Because
> this project defines two variants, omitting the name fails with
> *"cannot infer workshop name: multiple workshops found"*.
> The examples below use `renesas-resolute`; swap in `renesas-noble` if that is
> the variant you launched.

| Command | Does | Output |
|---------|------|--------|
| `clone-kernel` | Clone/checkout the configured kernel repo | `kernel-src/` |
| `kernel-build-debs` | Ubuntu kernel `.deb` packages from `kernel-src/` (via `debian/rules`) | `out/deb/` |
| `kernel-build-snap` | Ubuntu Core kernel `.snap` from `kernel-src/` (via `snapcraft`) | `out/snap/` |
| `clone-gadget` | Clone `renesas-bootassets` (out of scope) | `gadget-src/` |
| `gadget-build` | Gadget snap from `gadget-src/` (out of scope) | `out/gadget/` |

### Examples

```
# 1) Clone the kernel source once (reads repo/ref from config/workshop.yaml)
workshop run renesas-resolute -- clone-kernel

# 2) Build the Debian packages (reuses kernel-src, no re-clone)
workshop run renesas-resolute -- kernel-build-debs

# ...or the kernel snap (also reuses kernel-src)
workshop run renesas-resolute -- kernel-build-snap

# Build for armhf without editing config
WORKSHOP_ARCH=armhf workshop run renesas-resolute -- kernel-build-debs

# Refresh the source to the latest ref, then rebuild
workshop run renesas-resolute -- clone-kernel
workshop run renesas-resolute -- kernel-build-debs

# Gadget (out of scope): clone then build
workshop run renesas-resolute -- clone-gadget
workshop run renesas-resolute -- gadget-build
```

Every command supports `--help`:

```
workshop run renesas-resolute -- kernel-build-debs --help
```

---

## 5. Outputs

```
out/
├── deb/
│   ├── *.deb
│   └── metadata/          # .changes, .buildinfo, packages.txt
├── snap/
│   ├── *.snap
│   └── metadata/          # snaps.txt
└── gadget/                # gadget snap (out of scope)
    └── *.snap
```

A command only reports success **after its output is validated**
(e.g. the `.deb` is structurally readable and arch-correct with a
`linux-image` containing a kernel; the `.snap` is `type: kernel` with kernel
content). If validation fails, the command exits non-zero.

---

## 6. Environment overrides

Set these inline before `workshop run`:

| Variable | Applies to | Effect |
|----------|-----------|--------|
| `WORKSHOP_ARCH` | both | Override `toolchain.arch` (`arm64`/`armhf`/`amd64`). |
| `WORKSHOP_BOARD` | both | Override `silicon.soc` (`rzt2h`/`rzn2h`). |
| `SKIP_CLEAN=1` | debs | Skip the initial `debian/rules clean`. |
| `SKIP_CHOWN=1` | debs | Skip the pre-build ownership reset. |
| `SKIP_BUILD_DEPS=1` | debs | Skip `apt-get build-dep`. |
| `BUILDPACKAGE_OPTS` | debs | Extra flags for `dpkg-buildpackage` (e.g. `-j8`). |
| `SNAPCRAFT_OPTS` | snap | Extra flags for `snapcraft pack`. |

---

## 7. Rebuilding / cleaning

- **Build commands never clone or fetch.** They use the existing `kernel-src/`
  as-is, so you can rebuild repeatedly with no network access.
- To update the source to the latest of the configured ref (or after changing
  `kernel.ref` in `config/workshop.yaml`), re-run `clone-kernel` — it fetches
  and re-checks-out.
- To force a completely fresh clone, remove the tree first:
  ```
  rm -rf kernel-src
  workshop run renesas-resolute -- clone-kernel
  ```
- Runtime directories (`out/`, `kernel-src/`, `gadget-src/`, `cache/`,
  `build/`) are gitignored.

---

## 8. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `cannot infer workshop name: multiple workshops found` | You omitted the workshop name. Use `workshop run renesas-resolute -- <command>` (or `renesas-noble`). |
| `kernel-src not found` | You haven't cloned yet — run `workshop run <workshop> -- clone-kernel`. |
| `git clone failed` / permission denied | Private repo without auth: check `ssh-add -l` shows a key and connect the plug (`workshop connect <workshop>/deb-sdk:ssh-agent`). Public `https://` repos need nothing. |
| `debian/rules not found` | The configured `kernel.ref` is not an Ubuntu kernel packaging tree — check `kernel.repository` / `ref` in `config/workshop.yaml`, then re-run `clone-kernel`. |
| `No snapcraft.yaml found` (snap) | The kernel repo does not ship `snap/snapcraft.yaml` for the checked-out ref. |
| Permission denied during `debian/rules clean` | A prior root snap build left root-owned files; the deb command resets ownership automatically (disable with `SKIP_CHOWN=1`). |
| initrd chroot fails | qemu binfmt not registered; provisioning normally handles this — re-run the command (it re-registers) or re-launch. |
| health check fails | Missing toolchain/snapcraft channel — see the `check-health` output; usually resolved by re-running provisioning. |

---

## 9. Project layout

```
renesas/
├── config/
│   └── workshop.yaml         # declarative "what to build" (the only config)
├── sdk/
│   ├── common/               # shared helpers + clone-kernel
│   │   ├── bin/clone-kernel
│   │   ├── workshop.sh       # config parse, logging, toolchain
│   │   └── source.sh         # clone / require source
│   ├── deb/                  # Debian Packaging SDK  → kernel-build-debs
│   └── snap/                 # Snap Packaging SDK    → kernel-build-snap
├── tools/gadget-build        # gadget clone+build (out of scope)
├── .workshop/                # workshop + SDK definitions and setup hooks
├── ARCHITECTURE.md           # how the pieces fit together (start here)
├── DESIGN.md                 # contract divergences + rationale
└── README.md                 # this file
```
