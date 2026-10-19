from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import check_signatures


class SignatureVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gpg = shutil.which("gpg")
        cls.git = shutil.which("git")
        if cls.gpg is None or cls.git is None:
            raise unittest.SkipTest("signature tests require git and GnuPG")
        cls.key_store = tempfile.TemporaryDirectory(prefix="envman-signature-test-keys-")
        base = Path(cls.key_store.name)
        cls.trusted_home = base / "trusted-home"
        cls.other_home = base / "other-home"
        cls.trusted_home.mkdir(mode=0o700)
        cls.other_home.mkdir(mode=0o700)
        cls.trusted_fingerprint = cls._generate_key(cls.trusted_home, "Trusted Test Key")
        cls.other_fingerprint = cls._generate_key(cls.other_home, "Other Test Key")
        cls.certificate = base / "trusted-public.asc"
        exported = cls._gpg(
            cls.trusted_home,
            "--armor",
            "--export",
            cls.trusted_fingerprint,
        )
        cls.certificate.write_bytes(exported.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "key_store"):
            gpgconf = shutil.which("gpgconf")
            if gpgconf is not None:
                for home in (cls.trusted_home, cls.other_home):
                    subprocess.run(
                        [gpgconf, "--homedir", str(home), "--kill", "gpg-agent"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        check=False,
                    )
            cls.key_store.cleanup()

    @classmethod
    def _gpg(cls, home: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
        assert cls.gpg is not None
        environment = os.environ.copy()
        environment["GNUPGHOME"] = str(home)
        result = subprocess.run(
            [cls.gpg, "--batch", "--no-tty", "--no-options", "--homedir", str(home), *args],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
        return result

    @classmethod
    def _generate_key(cls, home: Path, name: str) -> str:
        assert cls.gpg is not None
        environment = os.environ.copy()
        environment["GNUPGHOME"] = str(home)
        generated = subprocess.run(
            [
                cls.gpg,
                "--batch",
                "--no-tty",
                "--no-options",
                "--homedir",
                str(home),
                "--pinentry-mode",
                "loopback",
                "--passphrase",
                "",
                "--quick-generate-key",
                f"{name} <{name.lower().replace(' ', '.')}@example.invalid>",
                "rsa4096",
                "sign",
                "0",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        if generated.returncode != 0:
            raise RuntimeError(generated.stderr.decode("utf-8", errors="replace"))
        listing = cls._gpg(home, "--with-colons", "--fingerprint", "--list-keys")
        for line in listing.stdout.decode("utf-8", errors="strict").splitlines():
            fields = line.split(":")
            if fields[0] == "fpr":
                return fields[9]
        raise RuntimeError("generated test key has no fingerprint")

    def _git(self, repository: Path, *args: str, signer: str | None = None) -> str:
        assert self.git is not None and self.gpg is not None
        command = [self.git]
        if signer is not None:
            command.extend(
                [
                    "-c",
                    f"user.signingkey={signer}",
                    "-c",
                    f"gpg.program={self.gpg}",
                    "-c",
                    "gpg.format=openpgp",
                ]
            )
        command.extend(args)
        environment = os.environ.copy()
        if signer == self.trusted_fingerprint:
            environment["GNUPGHOME"] = str(self.trusted_home)
        elif signer == self.other_fingerprint:
            environment["GNUPGHOME"] = str(self.other_home)
        result = subprocess.run(
            command,
            cwd=repository,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result.stdout.strip()

    def _repository(self, temporary: str) -> Path:
        repository = Path(temporary) / "repo"
        repository.mkdir()
        self._git(repository, "init", "--quiet")
        self._git(repository, "config", "user.name", "Signature Test")
        self._git(repository, "config", "user.email", "signature-test@example.invalid")
        return repository

    def _commit(self, repository: Path, message: str, signer: str | None = None) -> str:
        index = len(list(repository.glob("file-*.txt")))
        (repository / f"file-{index}.txt").write_text(f"{message}\n", encoding="utf-8")
        self._git(repository, "add", f"file-{index}.txt")
        args = ["commit", "--quiet", "-m", message]
        if signer is not None:
            args.insert(1, "-S")
        self._git(repository, *args, signer=signer)
        return self._git(repository, "rev-parse", "HEAD")

    def _verify(self, repository: Path, commit: str, tag: str | None = None) -> None:
        check_signatures.verify_signatures(
            commit,
            tag,
            repository=repository,
            certificate_path=self.certificate,
            expected_fingerprint=self.trusted_fingerprint,
        )

    def test_rejects_unsigned_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="envman-signature-test-repo-") as temporary:
            repository = self._repository(temporary)
            commit = self._commit(repository, "unsigned change")
            with self.assertRaises(check_signatures.SignatureVerificationError):
                self._verify(repository, commit)

    def test_rejects_commit_signed_by_another_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="envman-signature-test-repo-") as temporary:
            repository = self._repository(temporary)
            commit = self._commit(repository, "wrong signer", self.other_fingerprint)
            with self.assertRaises(check_signatures.SignatureVerificationError):
                self._verify(repository, commit)

    def test_rejects_lightweight_tag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="envman-signature-test-repo-") as temporary:
            repository = self._repository(temporary)
            commit = self._commit(repository, "signed commit", self.trusted_fingerprint)
            self._git(repository, "tag", "v-test-lightweight", commit)
            with self.assertRaisesRegex(check_signatures.SignatureVerificationError, "lightweight"):
                self._verify(repository, commit, "v-test-lightweight")

    def test_rejects_signed_tag_that_points_to_another_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="envman-signature-test-repo-") as temporary:
            repository = self._repository(temporary)
            selected = self._commit(repository, "selected commit", self.trusted_fingerprint)
            tagged = self._commit(repository, "different commit", self.trusted_fingerprint)
            self._git(
                repository,
                "tag",
                "-s",
                "-m",
                "signed tag",
                "v-test-mismatched",
                tagged,
                signer=self.trusted_fingerprint,
            )
            with self.assertRaisesRegex(check_signatures.SignatureVerificationError, "does not point"):
                self._verify(repository, selected, "v-test-mismatched")

    def test_accepts_signed_commit_and_annotated_tag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="envman-signature-test-repo-") as temporary:
            repository = self._repository(temporary)
            commit = self._commit(repository, "signed release source", self.trusted_fingerprint)
            self._git(
                repository,
                "tag",
                "-s",
                "-m",
                "signed release tag",
                "v-test-valid",
                commit,
                signer=self.trusted_fingerprint,
            )
            self._verify(repository, commit, "v-test-valid")


if __name__ == "__main__":
    unittest.main()
