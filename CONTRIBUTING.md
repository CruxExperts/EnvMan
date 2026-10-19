# Contributing

Use [GitHub Issues](https://github.com/CruxExperts/envman/issues) for reproducible defects and feature proposals. Use [GitHub Discussions](https://github.com/CruxExperts/envman/discussions) for questions and open-ended design discussion. Keep changes focused and describe the observable behavior they affect.

## Development setup

Envman targets Python 3.12 and pins its `uv` development workflow:

```bash
uv sync --locked --group dev
```

Install the repository hooks for local commit and push checks:

```bash
git config core.hooksPath .githooks
```

## Checks

Run the tests that cover your change. The repository test suite can be run with:

```bash
uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'
```

Do not include credentials, managed environment values, backup passwords, private paths, or machine-specific output in commits, issues, or pull requests. Update public documentation when a user-visible behavior or command changes. Do not hand-edit generated release artifacts; keep their source and generated form consistent.

Use [Conventional Commits](https://www.conventionalcommits.org/) for commit titles. Contributions are released under the [MIT License](LICENSE). Follow the [Code of conduct](CODE_OF_CONDUCT.md).

## Copyright and signed publication

Copyright (c) 2026 Crux Experts LLC. Source and documentation contributions use
the [MIT License](LICENSE); preserve third-party notices and the separate private
rights notices on original artwork. The
[repository policy](docs/governance/repository-policy.md) owns these boundaries.

Maintainer commits and annotated release tags must be RSA OpenPGP-signed with
the Crux Experts LLC key, primary fingerprint
`AF7968466B5B39C5E928FEFE716342D3EFBA5522`, using `pgp@cruxexperts.com` as the
committer and tagger email. Keep the private key outside the checkout; only the
public certificate belongs in version control. Contributor commits should be
signed with their own verified keys; the maintainer signs the integrated source.
GitHub's main-branch rule requires signed commits, while the release gate
additionally requires the specific publisher key.

For maintainer checkouts with that private key already available:

```bash
git config --local user.email pgp@cruxexperts.com
git config --local user.signingkey AF7968466B5B39C5E928FEFE716342D3EFBA5522
git config --local gpg.format openpgp
git config --local commit.gpgsign true
git config --local tag.gpgsign true
```

These settings do not create, import, or authorize access to a private key.
Do not use an unsigned fallback if signing fails. See
[release verification](docs/development/versioning-and-releases.md#tag-gated-github-workflow)
before publishing.
