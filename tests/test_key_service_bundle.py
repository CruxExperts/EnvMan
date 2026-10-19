"""Offline packaging includes the service's complete existing runtime."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("key_service_bundle", ROOT / "scripts/build_key_service_bundle.py")
assert SPEC is not None and SPEC.loader is not None
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class KeyServiceBundleTests(unittest.TestCase):
    def test_complete_runtime_and_manifest_without_host_installation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            bundle.build(output, 1234)
            config = json.loads((output / "key-service.json").read_text())
            self.assertEqual(config["service_uid"], 1234)
            self.assertTrue(config["allow_root_peer"])
            manifest = json.loads((output / "bundle-manifest.json").read_text())
            for name in ("_key_service.py", "_key_provider.py", "_secure_store.py"):
                self.assertTrue((output / "runtime" / name).is_file())
            self.assertTrue((output / "runtime/cryptography/__init__.py").is_file())
            self.assertEqual((output / "runtime/LICENSE.envman").read_bytes(), (ROOT / "LICENSE").read_bytes())
            for name, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            service = (output / "envman-key-service.service").read_text()
            self.assertIn("User=envman-keys", service)
            self.assertIn("LimitCORE=0", service)
            self.assertIn(" -I -B /usr/local/lib/", service)
            self.assertNotIn(str(ROOT), service)
            with self.assertRaises(FileExistsError):
                bundle.build(output, 1234)

    def test_root_is_not_a_service_account(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                bundle.build(Path(directory) / "bundle", 0)


if __name__ == "__main__":
    unittest.main()
