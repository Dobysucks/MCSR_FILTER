import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcsr_filter.backend import (
    BACKEND_NAME,
    PINNED_COMMIT,
    BackendArtifact,
    BackendInstallError,
    BackendInstaller,
    MINECRAFT_VERSION,
    trusted_artifact_manifest,
)


class BackendRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.payload = b"x" * 2048
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def artifact(self, commit=PINNED_COMMIT, version=MINECRAFT_VERSION):
        return BackendArtifact("https://trusted.invalid/backend.exe", self.digest, version, commit)

    def runner(self, path):
        return type("Result", (), {"returncode": 0, "stdout": "MCSeedFinder 26.2 " + PINNED_COMMIT, "stderr": ""})()

    def test_missing_trusted_artifact_fails_closed(self):
        installer = BackendInstaller(self.root)
        with self.assertRaisesRegex(BackendInstallError, "No trusted precompiled"):
            installer.install()

    def test_invalid_checksum_is_rejected_atomically(self):
        installer = BackendInstaller(self.root, self.artifact(), lambda _url, path: path.write_bytes(self.payload + b"!"), self.runner)
        with self.assertRaisesRegex(BackendInstallError, "checksum"):
            installer.install()
        self.assertFalse((self.root / BACKEND_NAME).exists())

    def test_invalid_version_or_commit_is_rejected(self):
        installer = BackendInstaller(self.root, self.artifact(commit="wrong"), lambda _url, path: path.write_bytes(self.payload), self.runner)
        with self.assertRaisesRegex(BackendInstallError, "does not match"):
            installer.install()

    def test_successful_install_and_offline_reuse(self):
        installer = BackendInstaller(self.root, self.artifact(), lambda _url, path: path.write_bytes(self.payload), self.runner)
        installed = installer.install()
        self.assertEqual(installed.name, BACKEND_NAME)
        self.assertEqual(installer.status(), "INSTALLED / VERIFIED")
        offline = BackendInstaller(self.root, self.artifact(), None, self.runner)
        self.assertEqual(offline.verify_installed(), installed)

    def test_provider_failure_is_not_hidden(self):
        def failed(_path):
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "startup failed"})()
        installer = BackendInstaller(self.root, self.artifact(), lambda _url, path: path.write_bytes(self.payload), failed)
        with self.assertRaisesRegex(BackendInstallError, "startup or identity"):
            installer.install()

    def test_program_version_is_separate_from_minecraft_version(self):
        artifact = BackendArtifact(
            "https://trusted.invalid/backend.exe",
            self.digest,
            MINECRAFT_VERSION,
            PINNED_COMMIT,
            "0.1.0",
        )
        runner = lambda _path: type("Result", (), {"returncode": 0, "stdout": "mcseed-finder 0.1.0", "stderr": ""})()
        installer = BackendInstaller(self.root, artifact, lambda _url, path: path.write_bytes(self.payload), runner)
        self.assertEqual(installer.install().name, BACKEND_NAME)

    def test_invalid_manifest_is_ignored(self):
        manifest = self.root / "backend.json"
        manifest.write_text('{"url":"x","sha256":"bad","version":"1.16.1","commit":"wrong"}', encoding="utf-8")
        self.assertIsNone(trusted_artifact_manifest(manifest))

    def test_user_backend_discovery_is_supported(self):
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            from mcsr_filter.backend import user_backend_dir
            self.assertEqual(user_backend_dir(), self.root / "MCSR26SeedFilter" / "backend")
