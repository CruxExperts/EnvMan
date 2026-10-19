---
title: Versioning and releases
---

# Versioning and releases

## Version source and checks

`VERSION` is Envman's canonical **source** version. Hatchling reads it for package metadata, and the CLI reads installed distribution metadata with a source-checkout fallback to `VERSION`. A source version can be ahead of the latest published release. Keep the README's explicitly labelled source display synchronized with:

```bash
uv run --locked --no-sync python scripts/version.py sync
uv run --locked --no-sync python scripts/version.py check
```

`sync` changes only the README source-version display. `check` requires exactly one source display matching `VERSION`, rejects the old ambiguous `Version` label, requires the dynamic latest-release badge linked to GitHub Releases, and verifies `INSTALLER_VERSION == VERSION`. The source and installer values must be strict `MAJOR.MINOR.PATCH` versions. It must not copy the source version into a published-release claim or require publication for every development commit.

GitHub's [latest published release](https://github.com/CruxExperts/envman/releases/latest), not `VERSION` or a Git tag alone, determines what the release installer downloads. Source skill documentation links use `main`; release asset generation pins those links to the release tag. Preserve dated changelog entries and recording provenance rather than advancing historical versions during source synchronization.

### Why the publication mismatch escaped checks

On 2026-10-19, GitHub's latest published release was v0.1.11 while the source tree was 0.1.12. The pre-push hook had advanced `VERSION` and the README together. The old quality gate checked that those values agreed, so it accepted an ambiguous public `Version: 0.1.12` display. The documentation checker only checked index membership; neither check established publication. CI was therefore green without a v0.1.12 release.

The corrected gate separates source identity from published identity. Regressions cover the misleading old display, missing or duplicate source displays, stale installer provenance, and preservation of the release badge during synchronization. Publication remains an explicit tag-gated operation; a source version bump never publishes a release.

## LocalSetup compatibility pin

Envman's agent target catalog is pinned to LocalSetup's latest stable release for repository policy, compliance, canonical write paths, supported client surfaces, and historical adapter transitions. This pin must be refreshed whenever LocalSetup publishes a stable release and must be current before Envman publishes:

```bash
uv run --locked --no-sync python scripts/sync_localsetup_skill_targets.py \
  --github-latest --check --verify-latest
```

To refresh after a LocalSetup release, run the same script without `--check`, review the generated `_release_protocol.py` catalog, render `install.py`, and run the release tests. The source release, `clients.yaml` hash, and `platforms.yaml` hash are embedded beside the catalog. The generated block is not hand-edited.

The inverse integration has a different rule: LocalSetup must resolve Envman from Envman's latest verified GitHub release manifest or installer and must not pin or vendor an Envman version.

## Patch-default planning

Plan the next release from the latest matching `vMAJOR.MINOR.PATCH` tag:

```bash
uv run --locked --no-sync python scripts/version.py plan
```

The planner examines active commits after that tag. A complete `Revert` commit and the exact commit it identifies do not contribute to the release. Merge commits and the release-version synchronization commit are ignored. Other non-Conventional subjects are reported as warnings rather than silently treated as release intent.

Every remaining Conventional Commit defaults to a patch bump. A commit body can set explicit intent with one trailer:

```text
Release-Type: major
Release-Type: minor
Release-Type: patch
Release-Type: none
```

The highest explicit or default intent wins across the release batch. A `BREAKING CHANGE:` or `type!:` marker requires an explicit `Release-Type:` trailer; the planner reports a warning when the marker has no explicit intent. Review the JSON result and warnings before changing `VERSION`.

## Tag-gated GitHub workflow

After updating `VERSION`, synchronizing the README source display, rendering the installer and agent skill, and moving the relevant `Unreleased` changelog entries into a versioned section, create a version-matching tag for the next release and push it only after the local checks pass:

```bash
git tag -s vX.Y.Z -m "Release vX.Y.Z"
git verify-tag vX.Y.Z
git push origin vX.Y.Z
```

The release workflow runs only for tags matching `v[0-9]*`. Its source gate requires the tag name without `v` to equal `VERSION` and the tagged commit to be an ancestor of `origin/main`. It then runs locked tests, `version.py check`, the documentation-index check, installer rendering parity, and agent-skill rendering parity.

Publish the verified signed source commit to `main` before pushing the tag.
Documentation is browsed directly on GitHub through the README and
[`docs/INDEX.md`](../INDEX.md). GitHub Pages is disabled and has no deployment
workflow. The optional local key service in v0.1.11 is experimental; release
publication does not qualify an administrator's systemd, SSH, or reboot setup.

## Build, assets, and publication

The build job sets `SOURCE_DATE_EPOCH` to the tagged commit timestamp, runs `uv build --no-build-isolation` twice, and requires byte-identical wheel and source-archive outputs. `scripts/release_assets.py` projects the version-locked canonical agent skill with release-tag documentation links, writes exact transitive runtime pins from `uv.lock`, a legacy `release-manifest.json`, a current `release-manifest-v2.json`, and `SHA256SUMS.txt`. The legacy manifest retains only wheel and constraint assets so immutable pre-skill installers can update; the v2 manifest is the default for the current installer and includes the verified skill asset. The publish job creates a draft GitHub release from the matching `CHANGELOG.md` section, uploads the wheel, source archive, installer, both manifests, constraints, agent skill, and checksum list, attests the release assets, and then clears the draft state.

The canonical release protocol and rendered installer must carry the same `INSTALLER_VERSION` as `VERSION`. A receipt records the version of the installer that created it, not whichever source checkout is newest. The installer and `envman update` verify the manifest, asset URL and hash, wheel metadata, compatibility, and runtime constraints. Installation records a private receipt under `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`; an update requires that receipt and refuses to switch providers or downgrade.
