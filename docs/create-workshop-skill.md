# create-workshop skill — Specification

## Purpose

An agent skill that guides a coding agent or contributor to instantiate a new
conformant Silicon Workshop from `workshop-template/`, given BSP analysis
inputs, without requiring knowledge of the internal workshop structure.

The skill performs live validation against Canonical's Launchpad kernel
repositories and the Ubuntu certified IoT device catalogue before any files
are written, ensuring the selected vendor/release/EVK combination is
supported and the kernel tag exists.

## Inputs

| Field | Description | Example |
|-------|-------------|---------|
| `vendor` | Silicon vendor identifier (lowercase) | `mediatek`, `qualcomm`, `renesas` |
| `soc` | SoC family identifier | `genio-510`, `sa8775p`, `rzt2h` |
| `evk_board` | Reference EVK board name | `genio-510-evk`, `iq-9075-evk` |
| `ubuntu_release` | Ubuntu series | `jammy`, `noble`, `resolute` |
| `kernel_repo` | Kernel git repository URL | `https://git.launchpad.net/~canonical-kernel/...` |
| `kernel_ref` | Kernel branch or tag | `Ubuntu-mtk-5.15.0-1041.49` |
| `kernel_flavour` | Kernel config flavour name | `mtk`, `qcom`, `renesas` |
| `toolchain_arch` | Target architecture | `arm64`, `armhf` |

## Behaviour

1. **Step A — Vendor selection**: fetches live Canonical kernel repos from
   Launchpad and cross-references with `ubuntu.com/certified/iot` to show only
   vendors with both a public kernel and certified devices.

2. **Step B — Release selection**: fetches available branches for the selected
   vendor's kernel repo; each branch name is a supported Ubuntu series.

3. **Step C — EVK selection**: fetches certified IoT devices for the selected
   vendor and presents them as EVK choices.

4. **Step D — Confirmation**: derives all remaining values automatically
   (kernel tag, toolchain, `core_base`) and presents a summary for approval.

5. **Generation**: copies `workshop-template/`, substitutes all
   `<placeholder>` tokens, generates `sdk/snap/snapcraft/snapcraft.yaml`,
   and registers the new workshop in `catalog.yaml`.

## Requirements

- The skill SHALL produce a complete workshop directory with **no remaining
  `<placeholder>` tokens** in any file after generation.
- The skill SHALL generate `sdk/snap/snapcraft/snapcraft.yaml` using
  `plugin: kernel` with `kernel-ubuntu-debian-package: true`.
- The skill SHALL add a new entry to `catalog.yaml` with `vendor`, `soc`,
  `evk`, `path`, and `ubuntu_releases` populated.
- The skill SHALL reject `kernel.repository` values containing embedded
  credentials (username:token patterns). `git+ssh://` URLs are permitted.
- The skill SHALL resolve the latest kernel release tag from Launchpad
  automatically when the user selects a branch, presenting it for confirmation.

## Toolchain notes

| Ubuntu series | clang | rustc | extra packages |
|---------------|-------|-------|----------------|
| resolute (26.04) | clang-21 (LLVM 21 repo) | 1.93.1 (native) | — |
| noble (24.04) | clang-18 | 1.75 (native) | `bindgen-0.65` |
| jammy (22.04) | clang-18 | 1.75 (native) | `bindgen-0.65`, `dwarfdump` |

> **Note:** Always read the kernel tree's `debian/control` `Build-Depends`
> before assuming a toolchain version — different kernel branches may differ.
