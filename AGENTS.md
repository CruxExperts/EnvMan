# Agent Instructions

This repo uses the universal agent repo shape.

## Shared Context

- Root `AGENTS.md` is the shared repo context for Codex, OMP, OpenCode, Cursor, and compatible agents.
- Reusable shared repo skills live under `.agents/skills/<skill>/SKILL.md` only when intentionally selected.
- Platform-specific overrides stay in platform-native files. Do not create repo-private OMP or Cursor configuration without an explicit repo override.

## Repo Profile

- Purpose: Portable terminal environment-variable manager
- Audience: Repository maintainers and agent collaborators
- Stack: python
- Package manager: uv

## Commands

- Test: `uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'`
- Build: `uv build --no-build-isolation`
- Deploy: `Release through the tag-gated GitHub Actions workflow`

## Skill Trust

External skills are not trusted from declarations alone. Install external skills only after fetch, vetting, normalization, sandbox testing when needed, lock update, and authorization roster update.

## Non-negotiable LocalSetup compatibility

- Envman is pinned to the latest stable LocalSetup release for repository policy, compliance, and supported agent skill shapes. Before every Envman release, the `LOCALSETUP_COMPATIBILITY_VERSION` catalog in `src/envman/_release_protocol.py` must equal GitHub's latest stable `CruxExperts/localsetup` release.
- `scripts/sync_localsetup_skill_targets.py` owns that generated catalog. Refresh it from the pinned LocalSetup source and run it with `--github-latest --check --verify-latest`; never hand-edit the generated block.
- The catalog derives canonical write paths from LocalSetup's `ls/config/platforms.yaml`, recognized native paths from `ls/config/clients.yaml`, and historical paths from `ls/core/client_registry/historical.py`. Preserve unmanaged content and the installer safety boundary when those sources change.
- LocalSetup's Envman integration must always resolve Envman through Envman's latest verified GitHub release manifest or installer. It must never pin, vendor, or hard-code an Envman version.

## Copyright, documentation, and publication policy

- Follow [repository policy](docs/governance/repository-policy.md), aligned with
  LocalSetup's MIT source-license and signed-publication baseline.
- Use `Copyright (c) 2026 Crux Experts LLC` for Envman source and documentation
  attribution. Keep `LICENSE`, README, package metadata, and contribution policy
  consistent. Preserve third-party notices and private original-asset rights;
  do not impose an MIT license on private artwork or relicense third-party work.
- Maintain documentation under the existing `docs/` library, update
  `docs/index.yaml` and `docs/INDEX.md` together, and distinguish source versions
  from published releases. Never hand-edit generated catalog or installer blocks.
- Maintainer commits and annotated release tags must be OpenPGP-signed with the
  RSA key `AF7968466B5B39C5E928FEFE716342D3EFBA5522`, using
  `pgp@cruxexperts.com` as committer/tagger email. Verify signatures before pushing.
  An unavailable key or failed signature is a hard stop, not permission for an
  unsigned fallback. Never commit private key material.
- Preserve existing GitHub protections; require signed commits on `main`.
  Release publication verifies both the exact source commit and annotated tag
  against the committed public certificate. Do not rewrite historical commits,
  tags, or immutable releases to apply a new policy.
