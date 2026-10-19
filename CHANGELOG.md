# Changelog

All notable changes are documented here.

## Unreleased

### Changed

- Refine the bracket-equals identity with coordinated vector wordmarks, compact
  icons, sculpted brand artwork, and dedicated wide and square social images.
- Add reproducible, ownership-tagged image exports and a versioned brand asset pack.

## [0.1.11] - 2026-10-19

![Envman: set variables once, load them in new shells](https://raw.githubusercontent.com/CruxExperts/EnvMan/v0.1.11/docs/assets/social-preview.png)

Keep your environment settings easy to use, with a new option to keep their
storage keys outside copied home directories.

### Added

- Add an optional local key service for Linux. An administrator can keep keys
  outside user homes, with separate access for each user and store. It needs no
  TPM, desktop keyring, or network service.
- Add explicit enrollment and migration that preserve existing keys and old
  snapshots, verify an independent recovery export, and report unfinished cleanup.
- Keep the retained shell loader working after CLI removal, including service
  retrieval and clear failure without partial assignments or a disk key cache.

### Changed

- Refresh the README, product artwork, banners, and social share image with
  clearer explanations of the benefits.
- Keep documentation on GitHub and retire the separate GitHub Pages site.
- Refresh the generated agent-skill catalog from the latest stable LocalSetup
  release and keep installer, skill, and package versions aligned.
- Refresh the pinned crypto runtime and build tools after version-specific
  advisory checks; keep release downloads and retained loaders on the same pins.

### Fixed

- Detect provider changes before a stale writer can overwrite a newer store.
- Make interrupted migrations recoverable without replacing keys or silently
  switching back to file storage.
- Preserve file-provider compatibility when provider metadata is absent.

### Experimental feature

The local key service is opt-in and requires separate administrator provisioning.
It protects passive home/configuration copies after cleanup. It does not protect
against code running as the enrolled user, root, service-account compromise,
hypervisor access, or full VM snapshots containing the keys. Actual systemd,
desktop/SSH, reboot, and VM startup-performance qualification remains outstanding.
See the [local key-service guide](https://github.com/CruxExperts/EnvMan/blob/v0.1.11/docs/guides/local-key-service.md)
before deployment. The existing file provider remains the default.

## [0.1.10] - 2026-09-24

### Added

- Add repository, global, and automatic agent-skill scopes with explicit targeting for all 20 agent shapes supported by LocalSetup 5.6.2.
- Let `envman update` install or refresh the verified latest-release skill, including when the Envman tool version is already current.
- Add a source-backed generator for canonical, native, and historical skill roots with release and registry hash provenance.

### Changed

- Make the latest stable LocalSetup release a mandatory Envman compatibility pin and verify it during CI and release preflight.
- Prefer the shared `.agents/skills` root while safely refreshing existing agent-native roots such as `.codex/skills` and `.opencode/skills`.
- Require LocalSetup integrations to resolve Envman through Envman's latest verified GitHub release without an Envman version pin.

## [0.1.9] - 2026-09-24

### Added

- Encrypt the managed environment file after its first save, with a separate private storage key and an explicit migration path for legacy plaintext snapshots.
- Add a cohesive Envman identity across the terminal UI, README, documentation site, social preview, icons, and repository artwork.

### Changed

- Redesign the terminal catalog and import preview with a clearer hierarchy, responsive row counts, stronger focus and selection cues, concise controls, and a colorless fallback.
- Rework the GitHub README and Pages site around task-focused installation, TUI, CLI, backup, storage, architecture, and testing routes.
- Expand rendering and storage coverage for focused rows, empty states, constrained terminals, encryption boundaries, and migration behavior.

### Fixed

- Use the terminal's default foreground color when available so values remain readable on light and dark terminal backgrounds.
- Align the CodeQL initialization and analysis actions to the same verified release.

## [0.1.8] - 2026-09-17

### Added

- Support current `uv` releases with a minimum requirement of `uv >=0.11` and no upper bound.
- Provide a single-command Ubuntu server installation path for Python 3.12 and `uv`.

### Changed

- Update the verified installer and release manifest compatibility metadata to remove the obsolete `uv <0.12` restriction.
- Refresh pinned build and runtime dependencies and GitHub Actions used by release and Pages workflows.

## [0.1.7] - 2026-07-27

### Added

- Add approved fallback encryption-key generation for encrypted backups.
- Add a centered TUI approval popup and an explicit CLI approval switch for key generation.
- Preserve explicit `ENVMAN_BACKUP_KEY` precedence and fail closed on malformed or insecure key files.

## [0.1.6] - 2026-07-22

### Added

- Publish the version-locked `envman-environment-variable-manager` agent skill with the release assets.
- Add optional public-installer skill installation with safe repository-local targets and rollback.

### Changed

- Keep the legacy release manifest compatible with pre-skill installers while current installers use the v2 manifest.

## [0.1.5] - 2026-07-20

### Fixed

- Add a release-check invariant that parses the canonical release protocol and rejects a stale installer provenance version unless `INSTALLER_VERSION == VERSION`.

## [0.1.4] - 2026-07-20

### Fixed

- Correct installer receipt provenance so receipts created by the changed installer record `installer_version: 0.1.4`.

## [0.1.3] - 2026-07-20

### Fixed

- Resolve the installed command through `uv tool dir --bin` before version verification, preventing a valid installation from being rolled back when the uv tool directory is absent from `PATH`.

## [0.1.2] - 2026-07-20

### Changed

- Redesign the terminal catalog as a full-height, index-free list.
- Replace numeric row shortcuts with Space-based multi-selection and grouped copy, delete, and encrypted-backup actions.
- Classify standalone and underscore-delimited `KEY` names as secrets while excluding `_API_KEY_ENV` references; apply length-aware masking (`4+4` for values 16 or more characters, `2+2` for 10-15, and `1+1` for 6-9) and reject secret values shorter than six characters.

### Fixed

- Clear the prompt row before every redraw so edited values cannot overlap stale text.
- Preserve Git unit and record separators while normalizing command output so an unreleased `feat:` commit receives the patch-default release plan.

## [0.1.1] - 2026-07-19

### Fixed

- Permit GitHub's signed release-asset redirects while preserving the trusted source and redirect-host boundary.

## [0.1.0] - 2026-07-19

### Added

- Terminal UI and scriptable CLI for persistent per-user environment variables.
- Validation and masking for names, URLs, paths, credentials, and sensitive values.
- Encrypted backup export and import.
- Verified GitHub-release installer and receipt-directed updater.
