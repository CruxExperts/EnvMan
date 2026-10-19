---
layout: default
title: Architecture
---

# Architecture

## Application boundary

Envman's runtime is a small Python 3.12 package. `src/envman/cli.py` owns the command-line parser, terminal UI, persistent environment store, validation and masking rules, shell-loader installation, import flows, and encrypted backups. `src/envman/_release_protocol.py` is intentionally standard-library-only because the committed `install.py` is generated from it and runs with `uv run --script`.

The project has no web framework, Node toolchain, linter dependency, or test-framework dependency in its runtime. Hatchling reads the single `VERSION` file for package metadata. The CLI reads installed distribution metadata and falls back to that source-checkout file when the package is not installed.

The small scripts have separate boundaries:

- `scripts/version.py` plans and checks the patch-default Conventional Commit release policy.
- `scripts/render_installer.py` renders `install.py` from `_release_protocol.py`.
- `scripts/sync_localsetup_skill_targets.py` renders the installer and updater's agent target catalog from the pinned latest stable LocalSetup source.
- `scripts/release_assets.py` creates the pinned runtime-constraints projection, release manifest, and SHA-256 list.
- `scripts/check_docs.py` checks that every machine-index path exists and is linked by `docs/INDEX.md`.

## Managed state

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` must be absolute when set. Otherwise Envman uses `$HOME/.config` and `$HOME/.local/state`. The managed file is `envman/environment.conf`; new saves use authenticated encryption and a separate storage key. Private atomic writes and timestamped tar-gzip snapshots replace the prior file. The utility directory is mode `0700` and unsafe symlink targets are rejected.

`envman init` installs loaders without adding a variable. The POSIX loader is `load-env.sh`; Envman adds guarded loader blocks to the supported profile files and writes a Fish loader at `fish/conf.d/envman.fish`. Existing profile content is preserved, and each profile is backed up before a loader block is added.

## Terminal UI and CLI

The TUI requires at least 80 columns by 18 rows. Its catalog capacity is computed from the current terminal height, so the catalog and detail view use the full available area instead of a fixed page index. Arrow keys move the current row, `[` and `]` scroll detail text, and Space toggles a variable in the multi-selection. `C` copies one source value to the selected targets, `D` deletes the selected group after confirmation, and `B` exports the selected group as an encrypted backup. At startup, when neither encryption-key source is configured, the TUI shows a centered approval modal before generating a private fallback key; `No` or `Esc` leaves state unchanged and encrypted-backup operations unavailable. Every prompt clears the prompt row before drawing its next frame.

The CLI exposes `init`, `target`, `check`, `update`, `list`, `get`, `import`, `export`, `import-backup`, `set`, `unset`, `rename`, `validate`, and `key`. Commands accept `--json` for stable machine-readable output. Sensitive values stay masked unless a caller explicitly supplies `--reveal`; `--force` and `--yes` suppress advisory warnings only, while key generation requires both `--generate` and `--approve-key-generation`.

Sensitivity is name- and value-aware. `KEY`-class names are sensitive, except names ending in `_API_KEY_ENV`, which are references to another managed variable. Sensitive values shorter than six characters are rejected. Masks show 1+1 characters for lengths 6-9, 2+2 for 10-15, and 4+4 for lengths of at least 16. URLs containing a password are also treated as sensitive.

Encrypted backups prefer the `ENVMAN_BACKUP_KEY` environment variable and otherwise use the private mode-`0600` fallback key file under the Envman configuration directory. The fallback is created only after the TUI approval modal or the CLI's explicit `key --generate --approve-key-generation` approval; malformed or insecure key files fail closed. Backups use an authenticated Fernet envelope with an scrypt-derived key. The JSON envelope contains the schema, version, creation time, KDF parameters, and ciphertext. Import validates the envelope and previews selected changes before applying them.

## Release protocol

The generated installer and the `update` command share `_release_protocol.py`. They accept only the exact release-manifest schema for `CruxExperts/envman`, Linux x86_64, Python `>=3.12,<3.13`, and `uv >=0.11`. Manifest assets must use immutable GitHub release URLs and declare bounded sizes and lowercase SHA-256 hashes. Downloads accept only GitHub-controlled HTTPS redirects; the wheel's Envman name and version, and every runtime constraint pin, are checked before installation.

Installation uses `uv tool install --no-build` and writes a private receipt at `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`. The receipt records the installed version, provider, manifest URL, asset metadata, installer version, `uv` version, and timestamp. Replacing an existing Envman tool requires a valid Envman receipt; updates use the recorded provider and refuse a downgrade. A failed replacement attempts to restore the previous wheel and receipt.

The optional agent skill uses scope and target selection from the LocalSetup compatibility catalog. Envman pins that catalog to the latest stable LocalSetup release at release time. LocalSetup's canonical write paths determine new roots; active client skill surfaces and historical transitions determine which existing roots can be refreshed. The public installer and installed updater share the same resolver, containment checks, unmarked-file protection, atomic writes, and rollback behavior.

## Deterministic release assets

`install.py` must be rendered from the canonical protocol and committed without a diff:

```bash
uv run --locked --no-sync python scripts/render_installer.py
git diff --exit-code -- install.py
```

The LocalSetup compatibility pin must also match its source projection and GitHub's latest stable release:

```bash
uv run --locked --no-sync python scripts/sync_localsetup_skill_targets.py \
  --github-latest --check --verify-latest
```

The tag-gated GitHub release workflow sets `SOURCE_DATE_EPOCH` to the tagged commit timestamp, builds twice with `uv build --no-build-isolation`, and compares the wheel and source archive byte-for-byte. `scripts/release_assets.py` then writes exact runtime pins from `uv.lock`, legacy and v2 release manifests, the version-locked agent skill, and `SHA256SUMS.txt`. The publish job creates a draft release from the matching changelog section, attests every release asset, and makes the release public only after those steps succeed.

## Encrypted storage

New saves encrypt the complete rendered configuration, including comments and
assignment order, through `src/envman/_secure_store.py`. The storage format has a
versioned marker and an authenticated Fernet token. All variables are encrypted,
regardless of the display heuristic used for masking. Input size is bounded;
unknown versions, damaged ciphertext, unsafe paths, and incorrect keys fail
closed. Fernet still exposes creation time and approximate payload size. See the
[Fernet documentation](https://cryptography.io/en/latest/fernet/).

The first save creates a random storage key in
`${XDG_STATE_HOME:-$HOME/.local/state}/envman/storage.key`. The key file is
private, owned by the user, and separate from the managed configuration and
its automatic snapshots. It is not the `ENVMAN_BACKUP_KEY` credential. The file
provider works without a prompt in desktop, SSH, and unattended sessions. Its
boundary is a copy of the encrypted data without the key; copying both defeats
it. A keyring alone would not meet the shared desktop and unattended session
requirement unless every required session can unlock it. Hardware-backed keys
would require a platform-specific provider and access tests.

`EnvironmentStore` still owns values, validation, imports, and the TUI. It reads
old plaintext files when no storage key exists and encrypts them on the first save.
If a key already exists with a plaintext active file, normal loading fails closed;
`migrate-storage --apply` explicitly recovers and converts that interrupted state. New
automatic environment snapshots contain ciphertext. Earlier plaintext snapshots
remain sensitive until the explicit `migrate-storage --apply` operation converts
them; `envman check` reports them.
The backup export/import format remains separate, password-derived, and portable.
Its independent credential remains necessary for clean-home recovery if the
storage key is unavailable.

## Retained shell loader

POSIX and Fish loader scripts call a private retained decryptor to read and
validate the entire file before emitting assignments. The decryptor supports
legacy plaintext before a storage key exists and loads encrypted files with the storage
key. Shell wrappers import validated name/value pairs literally; they do not
execute variable contents as shell code or write a decrypted cache. A missing
key or invalid file produces no managed assignments. Existing values inherited
from the parent process are outside this guarantee.

The retained runtime includes its own copy of the decryptor, `cryptography`,
its CFFI backend, and supporting packages with their license metadata. It remains
in the private configuration directory when the Envman tool is uninstalled. It requires the
Python interpreter named in the generated loader; removing that interpreter or
the retained runtime stops new shell loading. Installing a new loader runtime
on a later save or init does not remove older runtime versions that a previous
loader may still reference.

## Storage and recovery limits

Private atomic writes use unpredictable exclusive temporary files, no-follow
opens, ownership and mode checks, file and directory synchronization, and
atomic replacement. Snapshot names include subsecond time and random bytes to
avoid same-second collisions. Authentication detects accidental damage or
unauthorized changes to a ciphertext, but it does not detect rollback to an
older valid snapshot. Envman writers use a private file lock and compare the
loaded file fingerprint before replacement; a stale writer must reload instead
of silently replacing a newer save.

The first save does not erase existing plaintext snapshots, external backups,
or filesystem copies. The explicit migration command verifies and replaces
historical environment archives, preserving their filenames. It leaves profile
snapshots alone. Removing a file cannot guarantee erasure from SSD media
or filesystem snapshots. Keep an independent encrypted export and test recovery
on a clean home before relying on the storage key alone. Values necessarily
become plaintext in process memory and the process environment when loaded;
root or a process acting as the unlocked user can retrieve them.

## Proposed hardware-independent key isolation

**Status: PROPOSAL, 2026-10-19. Not implemented.** The requirement is automatic
loading on ordinary Linux desktops, VPS hosts, and virtual machines, including
SSH and unattended jobs after reboot. No TPM, desktop login, recurring password,
or network service should be required. One-time administrator provisioning is
the deployment cost of the stronger local mode; installations without that
authority retain the current file-key mode and its stated protection boundary.

### Recommended boundary

Keep the current authenticated encrypted configuration. Move its random storage
key out of the user's home and into a small local key service running under a
dedicated non-login service account. Its key directory is mode `0700`, with
mode-`0600` per-user key records, under an administrator-provisioned system state
directory such as `/var/lib/envman-keys`. The daemon needs no root privileges,
network listener, shell execution, or access to users' configuration files.
Administrator-owned service code and configuration must not import executable
code from an enrolled user's checkout or tool environment.

Envman and the retained shell loader request the enrolled user's existing key
over a local Unix stream socket, decrypt in memory, and load variables as today.
Use kernel-provided `SO_PEERCRED` credentials to authorize the connected user;
never trust a username, UID, path, or environment variable supplied in a request.
The [Linux Unix socket documentation](https://man7.org/linux/man-pages/man7/unix.7.html)
describes this peer-identity mechanism. A request cannot select another user's
key. Scope each key to the authenticated UID and a random store identifier so
separate XDG stores remain independent; the identifier is not a credential.
Administrator enrollment and retirement own the UID-to-key associations;
UID reuse requires retirement and fresh enrollment, not inherited access.

Use a socket path under an administrator-controlled directory and verify the
server identity as well as the client identity. Bound request sizes, connection
counts, and timeouts; close connections after each request. Do not log keys,
place them in arguments or environment variables, or persist a client key cache.
Disable service core dumps and restrict its filesystem access. Memory and swap
handling still need evaluation; Python cannot promise reliable key zeroization.
Use systemd socket activation where available; other supported supervisors must
provide the same ownership and reboot behavior. Do not add a setuid helper or
passwordless sudo invocation to shell startup.
Server verification must account for socket activation: peer credentials for a
supervisor-created listener need not identify the eventual service account.

This improves protection against a copied user home, dotfile synchronization,
and accidental exposure of the configuration and user-state directories together.
It does **not** stop arbitrary code running as the enrolled user from requesting
the same key. It does not protect against root, service-account compromise,
hypervisor access, or a complete VM/disk snapshot containing the system keys.
It also does not revoke variables already inherited by running processes.
The benefit is separation of file access and backup boundaries, not isolation
from the user who is deliberately authorized to load every variable.

For full-VM-copy protection, a separate design must keep an unlocking secret
outside the VM, through external key custody or operator input. External custody
also needs a non-clonable or externally controlled authorization mechanism;
moving the key behind an API while leaving a reusable token in the same snapshot
does not solve that problem. That requirement introduces an external trust and
availability dependency and is outside this local, offline proposal.

### Integration and migration

Add a shared storage-key resolver used by `EnvironmentStore`, snapshot migration,
and the retained decryptor. Persist explicit provider selection; absent metadata
continues to mean the existing file provider. An unavailable selected service
must fail promptly without emitting partial assignments, generating a replacement
key, or silently reverting to the old file. Interactive shells remain usable;
automation must receive an actionable nonzero result rather than continue on an
assumption that secrets loaded. Existing inherited values remain outside that
guarantee.

Enrollment must transfer the same data key so historical encrypted snapshots
remain readable. Extend the existing preview/apply migration workflow: lock and
revalidate the store and provider, securely enroll the key, verify retrieval and
decryption, install compatible retained loaders, and atomically activate the
provider. Remove the original file key only after verification and activation;
until cleanup succeeds, report the migration as incomplete. Make interrupted
steps reconcilable without silently replacing either key. Provider changes must
participate in stale-writer detection alongside the document fingerprint.

Before retiring the file key, verify an independent encrypted export and its
separately retrievable recovery credential. Test restoration without the key
service on an isolated home. Old external copies of the original key remain
sensitive. Check alternate exposure paths too: an encrypted export copied with
its fallback `encryption.key`, or an old plaintext snapshot, defeats the intended
home-copy protection. The retained runtime must include the shared socket client and keep
working after CLI removal; removing the service is a separate operation requiring
an explicit migration or recovery plan. No host enrollment or key migration is
authorized merely by this proposal.

### Acceptance before implementation is released

- Prove ordinary desktop, SSH public-key login, and unattended loading after
  reboot without a desktop session, prompt, hardware dependency, or network.
- Prove one enrolled UID cannot retrieve another UID's key; reject forged
  request identities, untrusted endpoints, malformed messages, and unknown users.
  Verify separate stores for one UID and failure to decrypt a home-only copy
  without access to its original key service.
- Prove bounded failure when the service is unavailable and no partial exports,
  disk key cache, plaintext fallback, or secret-bearing diagnostic output.
- Exercise interrupted enrollment, concurrent writes/provider changes, old
  snapshot decryption, recovery export restoration, and retained loading after
  CLI removal. Review daemon isolation and endpoint authentication separately.
- Measure cold and warm shell startup overhead on a modest VM before choosing
  a timeout or claiming that the experience is friction-free.

The next implementation step is an isolated service/client prototype with
synthetic keys. Existing stores and host services must remain untouched until
the protocol and failure behavior pass those checks.
