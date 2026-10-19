---
layout: default
title: Local storage key service
---

# Local storage key service

**Status: implemented, pending isolated deployment acceptance.** This optional
Linux provider separates storage keys from user homes. It uses the existing
authenticated store and needs no TPM, desktop keyring, recurring prompt, or
network service. Ordinary installation remains in file-provider mode. Nothing
in the installer, updater, or shell loader provisions or enrolls a host.

The service runs as a dedicated non-root, non-login account. Its mode-0700
system state directory contains mode-0600 key records. Clients request a random
store ID; the server obtains the UID from Linux `SO_PEERCRED`. A UID cannot
choose another UID in the protocol. Separate stores for one UID have distinct
random IDs. IDs are identifiers, not passwords.

This protects passive home/configuration copies after migration cleanup. Code
acting as the enrolled user can request its keys. Root, service-account
compromise, hypervisor access, and full VM snapshots containing system keys are
outside the boundary. Variables already inherited by running processes remain
readable. Python cannot promise reliable key zeroization; swap, core-dump, and
host backup policy remain administrator responsibilities.

## Offline provisioning assets

Provisioning is a separate administrator deployment. Review and back up any
existing target configuration before replacing it. The following paths are
deployment defaults, not changes made by building the bundle:

- `/usr/local/lib/envman-key-service/runtime`: root-owned service and complete
  Python crypto runtime, independent of any enrolled user's tool environment.
- `/etc/envman/key-service.json`: root-owned, mode-0644 administrator settings.
- `/var/lib/envman-keys`: service-owned, mode-0700 key records, outside homes.
- `/run/envman-keys/key-service.sock`: root-created systemd listening socket.

First allocate a dedicated `envman-keys` account on the target, with no login
shell or password authentication. The bundle supplies this sysusers record:

```text
u envman-keys - "Envman storage key service" /var/lib/envman-keys /usr/sbin/nologin
```

From the locked source environment, build a fresh offline tree using the
target's assigned numeric service UID:

```bash
uv run --locked --no-sync python scripts/build_key_service_bundle.py \
  --service-uid SERVICE_UID --output /absolute/new/bundle-directory
```

This command creates files only in that new directory. It never creates an
account, copies files into system paths, starts a service, or enrolls a key.
`bundle-manifest.json` records the version, file hashes, and asset notice;
third-party license metadata is retained. No dependencies are added beyond the
locked runtime used by Envman. The source archive includes the builder; normal
release manifests and runtime constraint projections remain unchanged.

An administrator must review the tree, verify the manifest hashes, and install
it through the target's normal configuration management. Install `runtime/` at
the root-owned runtime path above, with directories mode 0755 and files 0644;
no file or ancestor may be writable by the enrolled user or service account.
Install the JSON settings under a root-owned mode-0755 `/etc/envman`, the two
unit files under `/etc/systemd/system`, and the sysusers record under
`/etc/sysusers.d`. Confirm the configured UID matches the dedicated account.
Create `/var/lib/envman-keys` for that account with mode 0700. Keep all executable
code, configuration, and their ancestor directories root-owned and free of
group/other write permission. Never run root administration from a user's
checkout, shell loader, writable virtual environment, or `PYTHONPATH`.

The unit uses `/usr/bin/python3.12 -I -B`, socket activation, a read-only service
filesystem, no capabilities, no core dumps, and bounded processes, descriptors,
memory, connections, and requests. The target must retain that interpreter.
After reviewing these settings, an administrator can reload systemd and enable
`envman-key-service.socket` for reboot persistence. The service starts on the
first request. No live deployment is performed by the repository tests.

Only systemd is currently supplied as a production supervisor. The client
checks the root-controlled socket path and peer identity before sending a
request. With socket activation, Linux may report the root listener creator;
the administrator configuration explicitly permits this case. The daemon
validates exactly one inherited descriptor, its process association, Unix stream
type, listening state, bound path, and root socket ownership. Another supervisor
needs equivalent reviewed provisioning and separate acceptance evidence.

## Explicit enrollment and migration

Use synthetic data to qualify a new deployment before enrolling real stores.
Keep an independent encrypted recovery export and its separately retrievable
credential. An export copied together with its `encryption.key` fallback is
recoverable by anyone who obtains that home copy. `check` reports this alternate
exposure and historical plaintext snapshots. External copies and storage
remnants cannot be erased by migration.

Preview the provider transition, then explicitly prepare it:

```bash
envman migrate-storage --provider service --json
envman migrate-storage --provider service --prepare --apply --json
```

Preparation preserves the existing data key, converts legacy plaintext storage
and environment snapshots, and records a secret-free pending store ID and key
fingerprint. It prints the exact root administrator enrollment instruction.
Enrollment reads the existing key through a bounded file descriptor, never a
command argument or environment variable. The command shape is:

```text
/usr/bin/python3.12 -I -B /usr/local/lib/envman-key-service/runtime/_key_service.py admin-enroll --uid UID --store-id UUID --key-fd FD
```

The administrator must verify the intended account, numeric UID, store ID, and
key source before dispatching that instruction. The public retrieval socket
cannot enroll, replace, generate, or retire keys. Repeating enrollment with the
same live key reconciles; a different key fails rather than replacing it.

If an administrator enrolled the wrong key, keep file mode and the original
`storage.key` intact. Verify `check --json` still reports the file provider,
record the pending store ID, and have root retire that exact UID/store pair.
Only after retirement, move the secret-free
`<config>/envman/storage-provider-migration.json` record to a separate recovery
location. Do not move the provider selection, encrypted data, snapshots, or key.
Run preparation again to obtain a fresh UUID and enroll from the verified old
key descriptor. This explicit reconciliation never replaces an immutable key
or silently rotates the pending identity. Do not use it for an active service
or cleanup-pending transition; resume those operations normally.

After enrollment, supply `ENVMAN_BACKUP_KEY` through a trusted mechanism and
activate the provider:

```bash
envman migrate-storage --provider service --apply \
  --recovery-export /absolute/recovery-export.json --remove-file-key --json
envman check --json
```

Provider migration requires the explicitly supplied backup credential; it does
not use the home `encryption.key` fallback. It verifies the independent export
against all current values, retrieves and compares the enrolled data key,
verifies active and historical ciphertext, installs the compatible retained
loader, and atomically selects the service. Original file-key removal happens
last. Software verifies decryption but cannot prove that the operator can
retrieve the recovery credential independently; keep it outside the home and
the service and test restoration on a separate clean home.

Activation requires `--remove-file-key`. A cleanup interruption keeps its
obligation visible; home-copy protection is incomplete while the old storage
key remains. An interrupted operation retains its pending record; rerun the same explicit
operation after inspecting `check`. Conflicting data, keys, provider changes,
or store IDs fail instead of being overwritten. Writers compare both the
document and selected provider under the same store lock. No selected-service
failure silently falls back, creates replacement keys, or persists a client
key cache. CLI operations fail and retained loaders emit no partial assignments.

## Retirement and recovery

Before disabling the service, explicitly return an accessible store to file
mode, or restore its independent encrypted export onto a clean home:

```bash
envman migrate-storage --provider file --apply \
  --recovery-export /absolute/recovery-export.json --json
```

Returning to file mode preserves the same key and intentionally restores the
weaker file-copy boundary. It leaves service enrollment intact. Retire the
record separately, using the exact UID and previous store ID recorded during
migration:

```text
/usr/bin/python3.12 -I -B /usr/local/lib/envman-key-service/runtime/_key_service.py admin-retire --uid UID --store-id UUID
```

Retirement is terminal for that UID/store pair. Fresh enrollment needs a fresh
random store ID. Retire all old associations before deleting, reassigning, or
recreating an account. Enrollment binds the passwd identity as well as UID;
changed records fail closed. Linux exposes no account-creation generation
through peer credentials, so recreating identical passwd fields without
retirement cannot be distinguished automatically. Account lifecycle management
must enforce this retirement boundary. Changes to passwd fields also require
planned migration and fresh enrollment.

The service state and a backup stored on the same VM are not independent
full-VM recovery. A full snapshot copies both ciphertext and system keys. Full
VM-copy protection needs an unlocking secret and authorization outside that VM
and is outside this offline local design.

## Acceptance evidence and limits

Tests use synthetic keys and isolated homes. Real Unix-socket tests exercise
kernel peer credentials; fixture tests explicitly inject endpoint trust,
account identity, or administrator authority where noted. They do not enroll
this machine or install a system service. Migration and retained-loader tests
cover failure without partial exports, provider changes, historical snapshots,
and recovery without the selected service.

Before release acceptance on a deployment, verify production systemd activation,
cross-UID denial, desktop terminal startup, SSH public-key login, unattended
loading after reboot, and cold/warm shell overhead on a modest isolated VM.
Repository tests do not establish those desktop, SSH, or reboot claims. See
[testing](../development/testing.md) for reproducible local commands and the
current evidence boundary.
