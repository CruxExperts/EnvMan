---
title: Testing
---

# Testing

## Locked development environment

The project targets CPython 3.12 and requires at least uv 0.11 for the development toolchain through `pyproject.toml` and `uv.lock`. Start from a clean checkout with:

```bash
uv sync --locked --group dev
```

The release workflow's authoritative test command discovers the `unittest.TestCase` classes below `tests/`:

```bash
uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'
```

Do not replace `--locked --no-sync` with an unconstrained environment when checking a release. The discovery command covers storage and shell-loader preservation, input validation and masking, TUI recovery and selection behavior, import and encrypted-backup round trips, version lookup, and release-protocol trust boundaries. Release-protocol tests inject transport, state roots, and command runners; they do not contact production GitHub or mutate a developer's real uv tools.

## Focused source checks

### Local key service

Run synthetic protocol, provisioning, and mapped-namespace tests with:

```bash
uv run --locked --no-sync python -m unittest discover -s tests -p 'test_key_service*.py' -v
```

The namespace test uses `unshare --user --map-auto --map-root-user --mount`
and a disposable chroot. It runs the daemon as UID 1, a client as UID 2, and
enrolls distinct synthetic stores for UIDs 2 and 3. It exercises real
`SO_PEERCRED`, production root-owned configuration/path validation, private
service-owned records, and the daemon's inherited-descriptor checks. No
endpoint trust or account checks are mocked in that test. The listener and
`LISTEN_PID`/`LISTEN_FDS` environment simulate systemd activation; this is not
evidence of an actual systemd deployment. It skips with a reason when mapped
namespaces are unavailable. Other unit fixtures explicitly inject account,
administrator, or endpoint trust and must not be described as cross-UID proof.

The bundle test verifies complete runtime packaging and recorded hashes without
installing anything. Provider migration and retained-runtime tests use temporary
homes and synthetic keys, including independent export restoration without the
service. No tests modify the operator's login files, enroll this machine, or
use real secrets. Desktop, SSH public-key sessions, unattended loading after
reboot, and cold/warm startup measurements on an isolated VM remain pre-release
deployment acceptance work; those platform results have not been established.

Local acceptance on 2026-10-19 passed the locked full suite: 190 tests, with
one optional Fish test skipped because Fish was unavailable. Source compilation,
documentation/index checks, version checks, skill and installer parity, wheel
and source-archive builds, and release-asset projections passed. Package
inspection confirmed the shared provider, service, and migration modules and
the source provisioning builder are included. Builds used a clean candidate
tree containing task-owned changes, excluding unrelated untracked skill
projections. The v0.1.11 release refreshes the locked crypto runtime and build
tools after exact-version advisory checks. Runtime constraints are generated
from the same lockfile used to build and validate the retained loader.

### Generated sources and documentation

Use these local source-integrity checks before opening a release tag. The release workflow runs the version, documentation, and installer-parity checks from this list after its locked test command:

```bash
uv run --locked --no-sync python -m py_compile src/envman/*.py scripts/*.py install.py
uv run --locked --no-sync python scripts/version.py check
uv run --locked --no-sync python scripts/check_docs.py
uv run --locked --no-sync python scripts/render_installer.py
git diff --exit-code -- install.py
```

`check_docs.py` treats `docs/index.yaml` as the machine source of truth and requires every indexed file to exist and be linked from `docs/INDEX.md`. Rendering must leave the committed installer unchanged; edit `_release_protocol.py`, not `install.py`, when the protocol changes.

`version.py check` also protects the distinction between source and published
versions: it rejects the ambiguous old README version display, requires one
matching source-version display and the dynamic GitHub latest-release badge,
and checks installer provenance. The version regressions exercise misleading,
missing, duplicate, and mismatched displays. Source skill links follow `main`;
release asset checks verify that the distributed skill instead uses the
version-specific documentation tag.

## Reproducible release checks

Before publishing, build the artifacts twice from the tagged commit timestamp and compare both outputs:

```bash
export SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
uv build --no-build-isolation --out-dir /tmp/release-a
uv build --no-build-isolation --out-dir /tmp/release-b
cmp /tmp/release-a/envman-*.whl /tmp/release-b/envman-*.whl
cmp /tmp/release-a/envman-*.tar.gz /tmp/release-b/envman-*.tar.gz
```

The release job then runs `scripts/release_assets.py` to generate exact runtime constraints, the manifest, and `SHA256SUMS.txt`. Verify the isolated wheel installation and the private install receipt before treating the release as ready.
