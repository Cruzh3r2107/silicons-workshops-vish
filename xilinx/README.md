# AMD Kria KV260 Silicon Workshop

Builds and packages the Ubuntu 24.04 `linux-xilinx` kernel for the AMD Kria
KV260 (K26 SOM + KV carrier), following
[`SILICON_WORKSHOP_CONTRACT.md`](SILICON_WORKSHOP_CONTRACT.md).

## Quick start

    workshop launch
    workshop exec -- kernel-build          # out/kernel/
    workshop exec -- kernel-build-debs     # out/deb/ (runs kernel-build first if needed)
    workshop exec -- kernel-build-snap     # out/snap/ (runs kernel-build-debs first if needed)

## Commands

| Command | Result |
|---|---|
| `kernel-build` | Clones the pinned Ubuntu kernel, applies `patches/`, `overlays/` and `kernel.config`, builds with Ubuntu's `debian/rules`, stages and validates `out/kernel/` |
| `kernel-clean` | Removes generated build state and `out/`; keeps the git clone and project inputs |
| `kernel-build-debs` | Runs `debian/rules binary-xilinx` on the validated build; writes and validates `out/deb/*.deb` (version suffix `+workshop1`) |
| `kernel-build-snap` | Publishes `out/deb/` as a pinned local apt archive and builds the Ubuntu Core 24 kernel snap with Snapcraft's `plugin: kernel` (binary-package path) and `plugin: initrd`; validates `out/snap/*.snap` |

Each command validates its outputs before succeeding and, when neither
`project.yaml` inputs nor SDK code have changed, reuses valid outputs instead
of rebuilding. On failure the failing stage is named and its log is under
`build/logs/`.

## Host requirements

- `qemu-user-static` on the host: the kernel snap's initrd is built in an
  arm64 chroot, which needs the host's aarch64 binfmt handler with the `F`
  flag. `kernel-build-snap` checks this by running a tiny arm64 program.
- Network access to the Ubuntu archive, ports.ubuntu.com, cdimage.ubuntu.com
  (initrd base) and the kernel git repository.

## Customising

Edit `project.yaml`; add patch files under `patches/` and device-tree overlay
sources (`*.dtso`) under `overlays/`, then list them in `project.yaml`.
`kernel.config` values are written to Ubuntu's annotations exactly as given, so
quote them in YAML (`CONFIG_FOO: 'm'`, `CONFIG_LOG_BUF_SHIFT: '18'`) and keep
Kconfig's own quotes for string options
(`CONFIG_CMDLINE: '"console=ttyPS1,115200"'`).
Hardware-design-derived device-tree content (from Vivado) is produced outside
this Workshop and supplied as `.dtso` source. No SDK code changes are needed.

Private repositories: configure git credentials (credential helper or SSH
agent) outside the Workshop; never put credentials in `project.yaml`.

## Development

    python3 -m unittest discover -s tests -t .

The SDKs live in `.workshop/<name>/`. Workshop installs a snapshot of them at
launch, so after editing SDK code run `workshop refresh` before re-running a
command in the Workshop. Changes to a `setup-base` hook need the Workshop to be
recreated (`workshop remove` then `workshop launch`).
