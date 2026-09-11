# Reserved: contract-compliant snap path (not yet used)

This directory is reserved for the contract-compliant Snap Packaging SDK path
described in `../../../DESIGN.md` § Divergences #2.

To make the snap build comply with `SILICON_WORKSHOP_CONTRACT.md` §8, place a
workshop-owned `snapcraft.yaml` here that:

- uses `parts.kernel.plugin: kernel`
- consumes the Debian SDK output (`out/deb/`) via a local flat `file://` APT
  archive and `kernel-ubuntu-binary-package: true`

Until then, `kernel-build-snap` builds the snap directly from the kernel repo's
own `snapcraft.yaml` (documented deviation).

Verify current plugin keys against the official docs before implementing:
https://documentation.ubuntu.com/snapcraft/latest/reference/plugins/kernel_plugin/
