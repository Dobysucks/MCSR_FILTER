from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PINNED_COMMIT = "9087c5dc64f2bc12d55609f44ff85fb5b14fc802"
MINECRAFT_VERSION = "26.2"
BACKEND_NAME = "mcseed-finder.exe"
BACKEND_PROGRAM_VERSION = "0.1.0"
TRUSTED_BACKEND_SHA256 = "79EE7CCB48F3F7ADEBEF06DF79FD314700A80B3FC74112819C1F6F9FDD328142"


class BackendInstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendArtifact:
    url: str
    sha256: str
    version: str
    commit: str
    program_version: str | None = None


def user_backend_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "MCSR26SeedFilter" / "backend"


class BackendInstaller:
    """Install only an explicitly trusted, pinned backend artifact.

    The current upstream commit publishes source but no verified Windows
    artifact, so ``artifact`` is intentionally None in production.
    """

    def __init__(
        self,
        install_dir: Path | None = None,
        artifact: BackendArtifact | None = None,
        downloader: Callable[[str, Path], None] | None = None,
        runner: Callable[[Path], subprocess.CompletedProcess[str]] | None = None,
    ):
        self.install_dir = install_dir or user_backend_dir()
        self.artifact = artifact
        self.downloader = downloader
        self.runner = runner or self._run_version

    @property
    def executable(self) -> Path:
        return self.install_dir / BACKEND_NAME

    def status(self) -> str:
        if not self.executable.exists():
            return "NOT INSTALLED"
        if self.artifact is None:
            return "INSTALLED / UNVERIFIED (no trusted artifact manifest)"
        try:
            self._validate(self.executable, self.artifact)
            return "INSTALLED / VERIFIED"
        except BackendInstallError:
            return "INSTALLED / NOT VERIFIED"

    def install(self) -> Path:
        if self.artifact is None or self.downloader is None:
            raise BackendInstallError(
                "No trusted precompiled MCSeedFinder 26.2 Windows artifact is published "
                f"for pinned commit {PINNED_COMMIT}. Build the pinned source with "
                "build_windows.ps1; no unverified download will be executed."
            )
        if self.artifact.version != MINECRAFT_VERSION or self.artifact.commit != PINNED_COMMIT:
            raise BackendInstallError("Trusted backend manifest does not match Minecraft 26.2 and the pinned commit.")
        self.install_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.install_dir.parent) as temp_dir:
            temporary = Path(temp_dir) / BACKEND_NAME
            try:
                self.downloader(self.artifact.url, temporary)
                self._validate(temporary, self.artifact)
                os.replace(temporary, self.executable)
            except Exception as exc:
                if isinstance(exc, BackendInstallError):
                    raise
                raise BackendInstallError(f"Backend download or startup failed: {exc}") from exc
        return self.executable

    def verify_installed(self) -> Path:
        if not self.executable.exists():
            raise BackendInstallError(f"Verified backend is not installed at {self.executable}.")
        if self.artifact is None:
            raise BackendInstallError(
                "The installed backend has no trusted published checksum/version manifest and cannot be executed."
            )
        self._validate(self.executable, self.artifact)
        return self.executable

    def _validate(self, path: Path, artifact: BackendArtifact) -> None:
        if not path.is_file() or path.stat().st_size < 1024:
            raise BackendInstallError("Backend artifact is missing or unreasonably small.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest.lower() != artifact.sha256.lower():
            raise BackendInstallError("Backend SHA-256 checksum does not match the trusted manifest.")
        result = self.runner(path)
        output = (result.stdout or "") + (result.stderr or "")
        expected_identity = artifact.program_version or MINECRAFT_VERSION
        expected_provenance = () if artifact.program_version else (artifact.commit,)
        if result.returncode != 0 or expected_identity not in output or any(value not in output for value in expected_provenance):
            raise BackendInstallError(
                "Backend startup or identity verification failed; the executable was not accepted."
            )

    @staticmethod
    def _run_version(path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(path), "--version", "--commit"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )


def trusted_artifact_manifest(path: Path) -> BackendArtifact | None:
    """Read a future signed/maintained manifest; never infer trust from a URL."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        artifact = BackendArtifact(**data)
    except (OSError, ValueError, TypeError):
        return None
    if artifact.commit != PINNED_COMMIT or artifact.version != MINECRAFT_VERSION:
        return None
    return artifact
