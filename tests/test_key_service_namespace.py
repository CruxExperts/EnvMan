"""Real peer credentials in disposable mapped Linux namespaces, when available."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


class KeyServiceNamespaceTests(unittest.TestCase):
    def test_real_cross_uid_and_production_endpoint_trust(self) -> None:
        unshare = shutil.which("unshare")
        if sys.platform != "linux" or unshare is None or os.getuid() == 0:
            self.skipTest("requires unprivileged Linux mapped user namespaces")
        prefix = [unshare, "--user", "--map-auto", "--map-root-user", "--mount"]
        probe = subprocess.run([*prefix, "true"], capture_output=True, timeout=10)
        if probe.returncode:
            self.skipTest("mapped user/mount namespaces unavailable: " + probe.stderr.decode(errors="replace")[:200])
        result = subprocess.run(
            [*prefix, sys.executable, str(Path(__file__).with_name("key_service_namespace_fixture.py"))],
            env={**os.environ, "ENVMAN_NAMESPACE_FIXTURE": "1"},
            capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(b"PASS real cross-UID", result.stdout)


if __name__ == "__main__":
    unittest.main()
