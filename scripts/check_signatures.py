#!/usr/bin/env python3
"""Verify Envman source signatures using only its committed maintainer certificate."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_CERTIFICATE = ROOT / ".github" / "keys" / "cruxexperts.asc"
EXPECTED_FINGERPRINT = "AF7968466B5B39C5E928FEFE716342D3EFBA5522"
CERTIFICATE_LIMIT = 1024 * 1024
PROCESS_TIMEOUT_SECONDS = 30
FULL_OID = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
FINGERPRINT = re.compile(r"^(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})$")
RSA_ALGORITHMS = {"1", "2", "3"}
RSA_SIGNING_ALGORITHMS = {"1", "3"}
FATAL_SIGNATURE_STATUSES = {
    "BADSIG",
    "ERRSIG",
    "EXPSIG",
    "EXPKEYSIG",
    "KEYEXPIRED",
    "NO_PUBKEY",
    "REVKEYSIG",
    "SIGEXPIRED",
}


class SignatureVerificationError(RuntimeError):
    """A source object did not meet the maintainer-signature policy."""


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SignatureVerificationError(f"required executable is unavailable: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SignatureVerificationError(
            f"command timed out after {PROCESS_TIMEOUT_SECONDS} seconds: {' '.join(args[:3])}"
        ) from exc


def _output(result: subprocess.CompletedProcess[bytes]) -> str:
    return (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()


def _public_key_fingerprints(
    gpg: str,
    home: Path,
    repository: Path,
    env: dict[str, str],
    certificate: bytes,
    expected_fingerprint: str,
) -> dict[str, str]:
    imported = _run(
        [gpg, "--batch", "--no-tty", "--no-options", "--homedir", str(home), "--import"],
        cwd=repository,
        env=env,
        input_bytes=certificate,
    )
    if imported.returncode != 0:
        raise SignatureVerificationError(f"could not import committed public certificate: {_output(imported)}")

    listing = _run(
        [
            gpg,
            "--batch",
            "--no-tty",
            "--no-options",
            "--homedir",
            str(home),
            "--with-colons",
            "--fingerprint",
            "--fingerprint",
            "--list-keys",
        ],
        cwd=repository,
        env=env,
    )
    if listing.returncode != 0:
        raise SignatureVerificationError(f"could not inspect imported public certificate: {_output(listing)}")

    keys: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    primary_fingerprint: str | None = None
    for line in listing.stdout.decode("utf-8", errors="replace").splitlines():
        fields = line.split(":")
        if fields[0] in {"pub", "sub"}:
            if len(fields) <= 3:
                raise SignatureVerificationError("GnuPG returned a malformed public-key record")
            current = {"type": fields[0], "bits": fields[2], "algorithm": fields[3]}
            if fields[0] == "sub":
                if primary_fingerprint is None:
                    raise SignatureVerificationError("GnuPG returned a subkey without its primary key")
                current["primary_fingerprint"] = primary_fingerprint
            keys.append(current)
        elif fields[0] == "fpr" and current is not None and "fingerprint" not in current:
            if len(fields) <= 9 or FINGERPRINT.fullmatch(fields[9]) is None:
                raise SignatureVerificationError("GnuPG returned a malformed public-key fingerprint record")
            current["fingerprint"] = fields[9].upper()
            if current["type"] == "pub":
                primary_fingerprint = current["fingerprint"]
                current["primary_fingerprint"] = primary_fingerprint

    primaries = [key for key in keys if key["type"] == "pub"]
    if len(primaries) != 1 or any("fingerprint" not in key for key in keys):
        raise SignatureVerificationError("committed certificate must contain exactly one complete public key")
    primary = primaries[0]
    if primary["fingerprint"] != expected_fingerprint.upper():
        raise SignatureVerificationError(
            "committed certificate primary fingerprint does not match the pinned maintainer key "
            f"{expected_fingerprint} (found {primary['fingerprint']})"
        )
    if primary["algorithm"] not in RSA_ALGORITHMS or primary["bits"] != "4096":
        raise SignatureVerificationError("pinned maintainer primary key must be RSA 4096-bit")
    if any(key["algorithm"] not in RSA_ALGORITHMS or key["bits"] != "4096" for key in keys):
        raise SignatureVerificationError("committed maintainer certificate must contain only RSA 4096-bit keys")

    secret = _run(
        [gpg, "--batch", "--no-tty", "--no-options", "--homedir", str(home), "--with-colons", "--list-secret-keys"],
        cwd=repository,
        env=env,
    )
    if secret.returncode != 0:
        raise SignatureVerificationError(f"could not inspect isolated GnuPG secret-key store: {_output(secret)}")
    if any(line.split(":", 1)[0] in {"sec", "ssb"} for line in secret.stdout.decode("utf-8", errors="replace").splitlines()):
        raise SignatureVerificationError("isolated GnuPG home unexpectedly contains private key material")
    return {key["fingerprint"]: key["primary_fingerprint"] for key in keys}


def _git_output(
    git: str,
    repository: Path,
    env: dict[str, str],
    *args: str,
) -> str:
    result = _run([git, *args], cwd=repository, env=env)
    if result.returncode != 0:
        detail = _output(result)
        raise SignatureVerificationError(detail or f"git {' '.join(args)} failed")
    return result.stdout.decode("utf-8", errors="replace").strip()


def _resolve_commit(git: str, repository: Path, env: dict[str, str], oid: str) -> str:
    if FULL_OID.fullmatch(oid) is None:
        raise SignatureVerificationError("--commit must be a full 40- or 64-character commit object ID")
    resolved = _git_output(git, repository, env, "rev-parse", "--verify", "--end-of-options", f"{oid}^{{commit}}")
    if resolved.lower() != oid.lower():
        raise SignatureVerificationError(f"selected object is not the exact commit {oid}")
    return resolved


def _verify_signature(
    git: str,
    gpg: str,
    repository: Path,
    env: dict[str, str],
    object_kind: str,
    object_name: str,
    expected_fingerprint: str,
    certificate_primary_by_fingerprint: dict[str, str],
) -> None:
    result = _run(
        [git, "-c", f"gpg.program={gpg}", "-c", "gpg.format=openpgp", f"verify-{object_kind}", "--raw", object_name],
        cwd=repository,
        env=env,
    )
    combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    statuses = [line.split() for line in combined.splitlines() if line.startswith("[GNUPG:] ")]
    valid = [status for status in statuses if len(status) > 1 and status[1] == "VALIDSIG"]
    fatal = [status[1] for status in statuses if len(status) > 1 and status[1] in FATAL_SIGNATURE_STATUSES]
    if result.returncode != 0 or fatal or len(valid) != 1:
        detail = "; ".join(fatal) or "no single valid OpenPGP signature was reported"
        diagnostics = _output(result)
        if diagnostics:
            detail = f"{detail}: {diagnostics[:600]}"
        raise SignatureVerificationError(f"{object_kind} {object_name} signature verification failed: {detail}")

    status = valid[0]
    if len(status) < 10 or FINGERPRINT.fullmatch(status[2]) is None or status[8] not in RSA_SIGNING_ALGORITHMS:
        raise SignatureVerificationError(f"{object_kind} {object_name} uses a malformed or non-RSA signature")
    signer_fingerprint = status[2].upper()
    signer_primary_fingerprint = certificate_primary_by_fingerprint.get(signer_fingerprint)
    if signer_primary_fingerprint is None:
        raise SignatureVerificationError(f"{object_kind} {object_name} signer is not present in the pinned certificate")
    primary_fingerprint = status[11].upper() if len(status) > 11 else signer_primary_fingerprint
    if FINGERPRINT.fullmatch(primary_fingerprint) is None:
        raise SignatureVerificationError(f"{object_kind} {object_name} reports a malformed primary fingerprint")
    if primary_fingerprint != signer_primary_fingerprint:
        raise SignatureVerificationError(f"{object_kind} {object_name} reports an inconsistent signer primary fingerprint")
    if primary_fingerprint != expected_fingerprint.upper():
        raise SignatureVerificationError(
            f"{object_kind} {object_name} was not signed by pinned primary key {expected_fingerprint}"
        )


def verify_signatures(
    commit: str,
    tag: str | None = None,
    *,
    repository: Path = ROOT,
    certificate_path: Path = PUBLIC_CERTIFICATE,
    expected_fingerprint: str = EXPECTED_FINGERPRINT,
) -> None:
    """Verify one exact commit and, optionally, its annotated tag.

    Certificate and fingerprint overrides are internal test seams; the command-line
    interface always uses the committed certificate and pinned production fingerprint.
    """
    if FINGERPRINT.fullmatch(expected_fingerprint) is None:
        raise SignatureVerificationError("expected primary fingerprint must be a full hexadecimal fingerprint")
    try:
        certificate = certificate_path.read_bytes()
    except OSError as exc:
        raise SignatureVerificationError(f"cannot read committed public certificate {certificate_path}: {exc}") from exc
    if not certificate or len(certificate) > CERTIFICATE_LIMIT:
        raise SignatureVerificationError(f"public certificate must be between 1 byte and {CERTIFICATE_LIMIT} bytes")

    git = shutil.which("git")
    gpg = shutil.which("gpg")
    if git is None or gpg is None:
        missing = "git" if git is None else "gpg"
        raise SignatureVerificationError(f"required executable is unavailable: {missing}")

    try:
        with tempfile.TemporaryDirectory(prefix="envman-signature-check-") as temporary:
            home = Path(temporary)
            home.chmod(0o700)
            env = os.environ.copy()
            env["GNUPGHOME"] = str(home)
            env.pop("GPG_AGENT_INFO", None)
            certificate_fingerprints = _public_key_fingerprints(
                gpg, home, repository, env, certificate, expected_fingerprint
            )
            resolved_commit = _resolve_commit(git, repository, env, commit)
            _verify_signature(
                git,
                gpg,
                repository,
                env,
                "commit",
                resolved_commit,
                expected_fingerprint,
                certificate_fingerprints,
            )

            if tag is not None:
                if not tag:
                    raise SignatureVerificationError("tag name must not be empty")
                _git_output(git, repository, env, "check-ref-format", f"refs/tags/{tag}")
                tag_ref = f"refs/tags/{tag}"
                annotated_type = _git_output(git, repository, env, "cat-file", "-t", tag_ref)
                if annotated_type != "tag":
                    raise SignatureVerificationError(f"tag {tag!r} is lightweight; an annotated signed tag is required")
                tag_commit = _git_output(
                    git, repository, env, "rev-parse", "--verify", "--end-of-options", f"{tag_ref}^{{commit}}"
                )
                if tag_commit.lower() != resolved_commit.lower():
                    raise SignatureVerificationError(f"tag {tag!r} does not point to selected commit {resolved_commit}")
                _verify_signature(
                    git,
                    gpg,
                    repository,
                    env,
                    "tag",
                    tag_ref,
                    expected_fingerprint,
                    certificate_fingerprints,
                )
    except SignatureVerificationError:
        raise
    except OSError as exc:
        raise SignatureVerificationError(f"signature verification could not access the repository: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Envman maintainer-signed commits and annotated release tags")
    parser.add_argument("--commit", required=True, help="full commit object ID to verify")
    parser.add_argument("--tag", help="optional annotated tag that must point to --commit")
    arguments = parser.parse_args(argv)
    try:
        verify_signatures(arguments.commit, arguments.tag)
    except SignatureVerificationError as exc:
        print(f"check_signatures: {exc}", file=sys.stderr)
        return 1
    verified = f"commit {arguments.commit}"
    if arguments.tag is not None:
        verified += f" and tag {arguments.tag}"
    print(f"Verified pinned maintainer signatures for {verified}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
