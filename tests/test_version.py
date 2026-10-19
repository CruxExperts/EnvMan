from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("envman_version", Path(__file__).parents[1] / "scripts" / "version.py")
assert SPEC is not None and SPEC.loader is not None
version_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(version_tool)


def _readme(source_version: str, badge: str = version_tool.LATEST_RELEASE_BADGE) -> str:
    return f"**Source version:** {source_version}\n\n{badge}\n"


def _write_repo(root: Path, current_version: str, readme: str, installer_version: str) -> None:
    (root / "VERSION").write_text(f"{current_version}\n", encoding="utf-8")
    (root / "README.md").write_text(readme, encoding="utf-8")
    protocol = root / "src" / "envman" / "_release_protocol.py"
    protocol.parent.mkdir(parents=True, exist_ok=True)
    protocol.write_text(f'INSTALLER_VERSION = "{installer_version}"\n', encoding="utf-8")


class VersionPolicyTests(unittest.TestCase):
    def test_fully_reverted_commit_does_not_contribute_a_bump(self) -> None:
        original = ("a1b2c3d4e5f6", "feat: add temporary behavior", "")
        revert = ("f6e5d4c3b2a1", 'Revert "feat: add temporary behavior"', "This reverts commit a1b2c3d4e5f6.")
        self.assertEqual(version_tool.active_records([revert, original]), [])

    def test_unrelated_commit_remains_active_after_revert(self) -> None:
        original = ("a1b2c3d4e5f6", "fix: retain behavior", "")
        keep = ("b2c3d4e5f6a1", "docs: clarify usage", "")
        revert = ("c3d4e5f6a1b2", 'Revert "fix: retain behavior"', "This reverts commit a1b2c3d4e5f6.")
        self.assertEqual(version_tool.active_records([revert, keep, original]), [keep])

    def test_plan_uses_latest_tag_as_the_release_batch_base(self) -> None:
        with (
            patch.object(version_tool, "version", return_value="0.1.2"),
            patch.object(version_tool, "latest_tag", return_value="v0.1.0"),
            patch.object(version_tool, "commit_records", return_value=[("a1b2c3d4e5f6", "fix: repair release protocol", "")]),
        ):
            self.assertEqual(version_tool.plan()["target"], "0.1.1")

    def test_unreleased_feature_with_empty_body_uses_patch_default_plan(self) -> None:
        completed = version_tool.subprocess.CompletedProcess(
            args=["git", "log"],
            returncode=0,
            stdout=f"{'a' * 40}\x1ffeat: repair release planning\x1f\x1e\n",
            stderr="",
        )
        with (
            patch.object(version_tool, "version", return_value="0.1.1"),
            patch.object(version_tool, "latest_tag", return_value="v0.1.1"),
            patch.object(version_tool.subprocess, "run", return_value=completed),
        ):
            result = version_tool.plan()
        self.assertEqual(result["bump"], "patch")
        self.assertEqual(result["target"], "0.1.2")


    def test_check_accepts_source_version_ahead_of_published_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_repo(root, "0.1.12", _readme("0.1.12"), "0.1.12")
            with patch.object(version_tool, "ROOT", root):
                self.assertEqual(version_tool.check(), 0)

    def test_check_rejects_legacy_version_even_with_correct_source_display(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            readme = "**Version:** 0.1.11\n\n" + _readme("0.1.12")
            _write_repo(root, "0.1.12", readme, "0.1.12")
            with patch.object(version_tool, "ROOT", root):
                with self.assertRaisesRegex(ValueError, r"ambiguous \*\*Version:\*\*"):
                    version_tool.check()

    def test_check_rejects_invalid_source_displays_and_release_badges(self) -> None:
        cases = {
            "missing source": (
                f"Release notes\n\n{version_tool.LATEST_RELEASE_BADGE}\n",
                r"exactly one \*\*Source version:\*\*",
            ),
            "duplicate source": (
                _readme("0.1.5") + "**Source version:** 0.1.5\n",
                r"exactly one \*\*Source version:\*\*",
            ),
            "mismatched source": (
                _readme("0.1.4"),
                "source version display must equal VERSION",
            ),
            "missing latest-release badge": (
                "**Source version:** 0.1.5\n",
                "canonical latest-release badge and link",
            ),
            "hard-coded published release": (
                _readme("0.1.5", version_tool.LATEST_RELEASE_BADGE.replace("/releases/latest)", "/releases/tag/v0.1.5)")),
                "canonical latest-release badge and link",
            ),
        }
        for case, (readme, error) in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_repo(root, "0.1.5", readme, "0.1.5")
                with patch.object(version_tool, "ROOT", root):
                    with self.assertRaisesRegex(ValueError, error):
                        version_tool.check()

    def test_sync_updates_only_source_field_and_preserves_release_badge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = (
                "# Project\n\n"
                "**Source version:** 0.1.11\n\n"
                f"{version_tool.LATEST_RELEASE_BADGE}\n"
            )
            expected = original.replace("**Source version:** 0.1.11", "**Source version:** 0.1.12")
            _write_repo(root, "0.1.12", original, "0.1.12")
            with patch.object(version_tool, "ROOT", root):
                self.assertEqual(version_tool.sync(), 0)
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), expected)

    def test_check_rejects_stale_installer_version_in_release_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_repo(root, "0.1.5", _readme("0.1.5"), "0.1.3")
            with patch.object(version_tool, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "INSTALLER_VERSION"):
                    version_tool.check()

    def test_installer_version_rejects_noncanonical_bindings(self) -> None:
        cases = {
            "missing": 'value = "0.1.5"\n',
            "duplicate": 'INSTALLER_VERSION = "0.1.5"\nINSTALLER_VERSION = "0.1.5"\n',
            "nested": 'def configure():\n    INSTALLER_VERSION = "0.1.5"\n',
            "rebound": 'INSTALLER_VERSION = "0.1.5"\nfor INSTALLER_VERSION in ("0.1.4",):\n    pass\n',
            "trivia-only": '# INSTALLER_VERSION = "0.1.5"\nnote = \'INSTALLER_VERSION = "0.1.5"\'\n',
        }
        for case, source in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                protocol = root / "src" / "envman" / "_release_protocol.py"
                protocol.parent.mkdir(parents=True)
                protocol.write_text(source, encoding="utf-8")
                with patch.object(version_tool, "ROOT", root):
                    with self.assertRaisesRegex(ValueError, "INSTALLER_VERSION"):
                        version_tool.installer_version()

if __name__ == "__main__":
    unittest.main()
