# Silicon Workshops

Toolkit for creating reproducible Ubuntu kernel build environments for silicon
partners, using GitHub Copilot and the [`workshop`](https://snapcraft.io/workshop)
tool.

## What's included

| Path | Purpose |
|------|---------|
| `workshop-template/` | Silicon-agnostic scaffold — copied into your project by `init` |
| `workshop-catalog/init` | One-shot installer script |
| `workshop-catalog/skills/` | Copilot skills installed into your project |
| `docs/` | Skill specifications |

## Requirements

- [GitHub Copilot](https://github.com/features/copilot) in VS Code (Agent mode)
- [`workshop` snap](https://snapcraft.io/workshop): `sudo snap install workshop --classic`
- Git

---

## Installation

Clone this repository once on your machine:

```bash
git clone https://github.com/canonical/silicons-workshops ~/silicons-workshops
```

Then run `init` from any project directory where you want to manage Silicon Workshops:

```bash
cd /path/to/your/project
~/silicons-workshops/workshop-catalog/init
```

`init` will:
1. Copy `workshop-template/` into your project
2. Install all Copilot skills into `.github/skills/`
3. Create `catalog.yaml` if it doesn't exist

**Running `init` again is safe** — it skips files that are already present.

---

## Creating your first workshop

Open your project in VS Code with GitHub Copilot enabled and type in the
Copilot chat panel (Agent mode):

```
create-workshop
```

The skill guides you through three steps:

**Step 1 — Vendor**: lists silicon vendors that have both a public Canonical
kernel on Launchpad *and* Ubuntu-certified IoT devices. Only vendors passing
both checks are shown.

**Step 2 — Ubuntu release**: lists available series (`jammy`, `noble`,
`resolute`) for the selected vendor's kernel repository.

**Step 3 — EVK**: lists Ubuntu-certified IoT devices for that vendor.

After confirmation the skill:
- Resolves the latest kernel release tag from Launchpad automatically
- Copies `workshop-template/` to `<vendor>-workshop/`
- Substitutes all placeholder values
- Generates `sdk/snap/snapcraft/snapcraft.yaml`
- Registers the workshop in `catalog.yaml`

---

## Launching a workshop

```bash
cd <vendor>-workshop/

# First time: clone the kernel source
workshop run <vendor>-<series> -- clone-kernel

# Build kernel .deb packages
workshop run <vendor>-<series> -- kernel-build-debs

# Build kernel snap
workshop run <vendor>-<series> -- kernel-build-snap
```

Built artefacts land in `out/deb/` and `out/snap/` respectively.

---

## Skill installed by `init`

| Skill | Purpose |
|-------|---------|
| `create-workshop` | Guided wizard — vendor / release / EVK → ready-to-launch workshop |

See [`docs/create-workshop-skill.md`](docs/create-workshop-skill.md) for the
full `create-workshop` skill specification.

---

## Updating

```bash
cd ~/silicons-workshops && git pull
cd /path/to/your/project && ~/silicons-workshops/workshop-catalog/init
```

`init` will update the skill files but will not overwrite your existing
workshops or `catalog.yaml`.
