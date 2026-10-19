from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import render_agent_skill
from scripts import release_assets


class ReleaseAssetsTests(unittest.TestCase):
    def test_assets_pin_published_skill_links_and_leave_canonical_links_on_main(self) -> None:
        version = (release_assets.ROOT / "VERSION").read_text(encoding="utf-8").strip()
        source_bytes = release_assets.SKILL_SOURCE.read_bytes()
        source_text = source_bytes.decode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            wheel = output / f"envman-{version}-py3-none-any.whl"
            constraints = output / "runtime-constraints.txt"
            wheel.write_bytes(b"wheel")
            constraints.write_text("cryptography==49.0.0\n", encoding="utf-8")

            assets = release_assets.assets(version, output)
            skill = output / "envman-environment-variable-manager-skill.md"
            published_text = skill.read_text(encoding="utf-8")
            doc_refs = re.compile(
                r"https://github\.com/CruxExperts/envman/blob/(main|v\d+\.\d+\.\d+)/docs/"
            )
            self.assertEqual(set(doc_refs.findall(source_text)), {"main"})
            self.assertEqual(set(doc_refs.findall(published_text)), {f"v{version}"})
            self.assertEqual(release_assets.SKILL_SOURCE.read_bytes(), source_bytes)
            self.assertEqual(release_assets.SKILL_LOCK_PATTERN.search(published_text).group("version"), version)
            self.assertEqual(assets["skill"]["filename"], skill.name)
            self.assertEqual(assets["skill"]["size"], skill.stat().st_size)
            self.assertEqual(assets["skill"]["sha256"], hashlib.sha256(skill.read_bytes()).hexdigest())

            self.assertEqual(assets["skill"]["url"], f"https://github.com/{release_assets.REPOSITORY}/releases/download/v{version}/envman-environment-variable-manager-skill.md")

    def test_main_emits_legacy_manifest_and_skill_manifest(self) -> None:
        version = (release_assets.ROOT / "VERSION").read_text(encoding="utf-8").strip()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / f"envman-{version}-py3-none-any.whl").write_bytes(b"wheel")
            with mock.patch.object(sys, "argv", ["release_assets.py", "--output", str(output), "--version", version]):
                self.assertEqual(release_assets.main(), 0)
            legacy = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
            current = json.loads((output / "release-manifest-v2.json").read_text(encoding="utf-8"))
            self.assertNotIn("skill", legacy["assets"])
            self.assertIn("skill", current["assets"])

    def test_skill_bytes_rejects_stale_release_version(self) -> None:
        current = (release_assets.ROOT / "VERSION").read_text(encoding="utf-8").strip()
        with self.assertRaises(ValueError):
            release_assets.skill_bytes("0.0.0" if current != "0.0.0" else "0.0.1")

    def test_skill_bytes_rejects_unlocked_source(self) -> None:
        original = release_assets.SKILL_SOURCE
        with tempfile.TemporaryDirectory() as temporary:
            replacement = Path(temporary) / "SKILL.md"
            replacement.write_text("---\nname: envman-environment-variable-manager\ndescription: test\n---\n", encoding="utf-8")
            release_assets.SKILL_SOURCE = replacement
            try:
                version = (release_assets.ROOT / "VERSION").read_text(encoding="utf-8").strip()
                with self.assertRaises(ValueError):
                    release_assets.skill_bytes(version)
            finally:
                release_assets.SKILL_SOURCE = original

    def test_renderer_check_rejects_stale_tagged_documentation_links(self) -> None:
        version = (release_assets.ROOT / "VERSION").read_text(encoding="utf-8").strip()
        source = release_assets.SKILL_SOURCE.read_text(encoding="utf-8")
        stale = source.replace("blob/main/docs/", f"blob/v{version}/docs/")
        self.assertNotEqual(stale, source)
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "SKILL.md"
            skill.write_text(stale, encoding="utf-8")
            with mock.patch.object(render_agent_skill, "SKILL_FILE", skill):
                self.assertEqual(render_agent_skill.main(["--check"]), 1)


if __name__ == "__main__":
    unittest.main()
