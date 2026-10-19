---
title: Repository ownership and publication policy
status: ACTIVE
owner_package: envman
last_updated: "2026-10-19"
---

# Repository ownership and publication policy

## Copyright and license

Copyright (c) 2026 [Crux Experts LLC](https://www.cruxexperts.com/).
Envman source code and documentation use the [MIT License](../../LICENSE),
matching LocalSetup's source-license baseline. The license grants permission to
use, modify, and distribute the software under its notice and warranty terms;
company ownership does not make MIT-licensed source proprietary.

Original visual assets have separate private rights notices in their embedded
metadata and [asset manifest](../assets/asset-manifest.json). Preserve those
notices and any third-party copyright or license terms. Do not apply the source
license to separately restricted artwork or claim ownership of third-party work.

Keep the root license, README, package author metadata, and contribution policy
consistent. Do not bulk-rewrite historical release documentation, screenshots,
or provenance records to make them look current.

## Documentation and LocalSetup compatibility

Use the existing `docs/` library and maintain its machine and human indexes
together: [index.yaml](../index.yaml) and [INDEX.md](../INDEX.md). Current guides
must describe the implemented behavior, distinguish experimental features, and
link to their owning references. Keep machine-specific evidence, credentials,
and private configuration outside tracked documentation.

The [release guide](../development/versioning-and-releases.md) owns source
versioning, published-release discovery, generated installer and skill parity,
and the latest-stable LocalSetup compatibility check. Reuse those owners rather
than copying LocalSetup's entire framework into this application repository.

## RSA OpenPGP signing

The maintainer publication identity is:

- Owner: Crux Experts LLC.
- Committer and tagger email: `pgp@cruxexperts.com`.
- Primary RSA4096 fingerprint:
  `AF7968466B5B39C5E928FEFE716342D3EFBA5522`.
- Tracked public certificate:
  [cruxexperts.asc](../../.github/keys/cruxexperts.asc).

Sign maintainer commits and annotated release tags. Verify the actual signature
and exact primary fingerprint before pushing; a display name, email, short key
ID, or generic GitHub Verified badge alone does not establish the publisher.
Signing failure stops publication. Do not export, commit, upload, or log the
private key or passphrase. Contributor commits use their own verified signing
identities; maintainer publication uses the pinned company key.

Git signatures cover the committed tree, including source, documentation,
artwork, and workflows. They do not require a detached signature file beside
every document. Release artifact integrity additionally uses the existing
checksum manifests and GitHub build attestations. This policy does not claim
that historical releases acquire new signatures or that artifact attestations
are company-key signatures.

The release workflow verifies the exact source commit and annotated tag in an
isolated public-only keyring before building. The tag must resolve to that
commit. The pre-push path signs automatic version-sync commits rather than
relying on a developer's global Git defaults. See
[contributor setup](../../CONTRIBUTING.md#copyright-and-signed-publication).

## GitHub governance

Keep `main` protected against deletion and force pushes, retain linear history,
and require signed commits. GitHub's signature rule accepts verified signer
identities; the release workflow separately enforces the company publisher key.
Preserve existing immutable-release and protected-tag controls. Private
vulnerability reporting, Issues, Discussions, pinned workflow actions, and the
repository's current documentation routes remain in place.

The [tracked GitHub policy](../../.github/repository-policy.json) owns the desired
main-branch ruleset. Use the owning LocalSetup GitHub repository workflow for
audit and scoped settings changes. Never weaken protections, change visibility,
or rewrite published history as a shortcut. Changing the publisher key is a
separately reviewed trust change, not an automatic key download.
