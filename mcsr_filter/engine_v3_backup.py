from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .config import FilterConfig, MINECRAFT_VERSION
from .backend import (
    BACKEND_NAME,
    BACKEND_PROGRAM_VERSION,
    PINNED_COMMIT,
    TRUSTED_BACKEND_SHA256,
    user_backend_dir,
)


class GenerationUnavailableError(RuntimeError):
    """Raised when exact Minecraft 26.2 verification is unavailable."""


@dataclass(frozen=True)
class ProviderSelfTest:
    verified: bool
    provider_name: str
    version: str
    message: str
    minecraft_version: str = MINECRAFT_VERSION
    commit: str = PINNED_COMMIT
    sha256: str = ""


class IMinecraft26WorldGenProvider(ABC):
    version = MINECRAFT_VERSION
    name = "unavailable"
    openTerrainSupported = False
    lavaPoolSupported = False

    @abstractmethod
    def self_test(self) -> ProviderSelfTest:
        raise NotImplementedError

    @abstractmethod
    def accepts(
        self,
        seed: int,
        filters: FilterConfig,
        pool: str = "overworld",
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def verify_seed(
        self,
        seed: int,
        pool: str,
        filters: FilterConfig,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_world_generation_version(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def find_lava_pool(
        self,
        seed: int,
        pool: str,
    ) -> dict[str, int] | None:
        raise NotImplementedError

    @abstractmethod
    def check_open_terrain(
        self,
        seed: int,
        pool: str,
        first: dict[str, Any],
        second: dict[str, Any] | None = None,
    ) -> bool:
        raise NotImplementedError


WorldGenerationProvider = IMinecraft26WorldGenProvider


class UnavailableMinecraft262Provider(
    IMinecraft26WorldGenProvider
):
    name = "No provider"

    def self_test(self) -> ProviderSelfTest:
        return ProviderSelfTest(
            False,
            self.name,
            "",
            "No verified Minecraft 26.2 backend is installed.",
        )

    def accepts(
        self,
        seed: int,
        filters: FilterConfig,
        pool: str = "overworld",
    ) -> bool:
        raise GenerationUnavailableError(
            "Minecraft Java 26.2 world-generation provider verification "
            "failed. Seed generation has been disabled to prevent "
            "inaccurate results."
        )

    def verify_seed(
        self,
        seed: int,
        pool: str,
        filters: FilterConfig,
    ) -> dict[str, Any]:
        raise GenerationUnavailableError(
            "No Minecraft Java 26.2 provider is available."
        )

    def get_world_generation_version(self) -> str:
        return MINECRAFT_VERSION

    def find_lava_pool(
        self,
        seed: int,
        pool: str,
    ) -> dict[str, int] | None:
        raise GenerationUnavailableError(
            "Lava-pool lookup is unavailable without the 26.2 backend."
        )

    def check_open_terrain(
        self,
        seed: int,
        pool: str,
        first: dict[str, Any],
        second: dict[str, Any] | None = None,
    ) -> bool:
        raise GenerationUnavailableError(
            "Open-terrain lookup is unavailable without the 26.2 backend."
        )


class MCSeedFinderProvider(IMinecraft26WorldGenProvider):
    name = "MCSeedFinder 26.2"

    STABLES_PIECE = (
        "bastion/hoglin_stable/ramparts/ramparts_3"
    )

    TREASURE_PIECE = (
        "bastion/treasure/ramparts/mid_wall_main"
    )

    BRIDGE_PIECE = (
        "bastion/bridge/starting_pieces/entrance"
    )

    def __init__(self, executable: Path):
        self.executable = executable
        self._verified = False

    def _run(
        self,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.executable), *args],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )

    def self_test(self) -> ProviderSelfTest:
        if not self.executable.exists():
            return ProviderSelfTest(
                False,
                self.name,
                "",
                f"Backend not found: {self.executable}",
            )

        try:
            if self.executable.name.lower() != BACKEND_NAME:
                return ProviderSelfTest(
                    False,
                    self.name,
                    "",
                    "Backend executable identity is not "
                    "mcseed-finder.exe.",
                )

            digest = hashlib.sha256(
                self.executable.read_bytes()
            ).hexdigest().upper()

            if digest != TRUSTED_BACKEND_SHA256:
                return ProviderSelfTest(
                    False,
                    self.name,
                    "",
                    "Backend SHA-256 does not match the "
                    "trusted pinned artifact.",
                    sha256=digest,
                )

            version = self._run("--version")
            structures = self._run(
                "list",
                "structures",
                "--json",
            )
            pieces = self._run(
                "list",
                "pieces",
                "--structure",
                "bastion_remnant",
            )

            program_output = (
                version.stdout or ""
            ) + (
                version.stderr or ""
            )

            if (
                version.returncode != 0
                or f"mcseed-finder {BACKEND_PROGRAM_VERSION}"
                not in program_output
            ):
                return ProviderSelfTest(
                    False,
                    self.name,
                    "",
                    "Backend did not report the trusted "
                    "mcseed-finder program version.",
                    sha256=digest,
                )

            if structures.returncode != 0:
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Structure registry self-test failed.",
                    sha256=digest,
                )

            available = json.loads(structures.stdout)

            required = {
                "village",
                "shipwreck",
                "desert_pyramid",
                "ruined_portal",
                "buried_treasure",
                "bastion_remnant",
                "fortress",
            }

            names = {
                str(item.get("name", item))
                if isinstance(item, dict)
                else str(item)
                for item in available
            }

            if not required.issubset(names):
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Required 26.2 structure registry entries "
                    "are missing.",
                    sha256=digest,
                )

            piece_text = (
                pieces.stdout or ""
            ) + (
                pieces.stderr or ""
            )

            required_pieces = (
                self.STABLES_PIECE,
                self.TREASURE_PIECE,
                self.BRIDGE_PIECE,
            )

            if any(
                piece not in piece_text
                for piece in required_pieces
            ):
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Required 26.2 Bastion subtype pieces "
                    "are missing from the backend.",
                    sha256=digest,
                )

            # Exercise every Overworld filter independently.
            overworld_filters = (
                FilterConfig(
                    village=True,
                    shipwreck=False,
                    desert_temple=False,
                    ruined_portal=False,
                    buried_treasure=False,
                    stables=False,
                    treasure=False,
                    bridge=False,
                    housing=False,
                    fortress=False,
                ),
                FilterConfig(
                    village=False,
                    shipwreck=True,
                    desert_temple=False,
                    ruined_portal=False,
                    buried_treasure=False,
                    stables=False,
                    treasure=False,
                    bridge=False,
                    housing=False,
                    fortress=False,
                ),
                FilterConfig(
                    village=False,
                    shipwreck=False,
                    desert_temple=True,
                    ruined_portal=False,
                    buried_treasure=False,
                    stables=False,
                    treasure=False,
                    bridge=False,
                    housing=False,
                    fortress=False,
                ),
                FilterConfig(
                    village=False,
                    shipwreck=False,
                    desert_temple=False,
                    ruined_portal=True,
                    buried_treasure=False,
                    stables=False,
                    treasure=False,
                    bridge=False,
                    housing=False,
                    fortress=False,
                ),
                FilterConfig(
                    village=False,
                    shipwreck=False,
                    desert_temple=False,
                    ruined_portal=False,
                    buried_treasure=True,
                    stables=False,
                    treasure=False,
                    bridge=False,
                    housing=False,
                    fortress=False,
                ),
            )

            for structure_filters in overworld_filters:
                report = self._check(
                    0,
                    "overworld",
                    structure_filters,
                )

                if (
                    report.get("version")
                    != MINECRAFT_VERSION
                    or report.get("seed") != 0
                    or "spawn" not in report
                ):
                    return ProviderSelfTest(
                        False,
                        self.name,
                        BACKEND_PROGRAM_VERSION,
                        "Overworld structure lookup failed.",
                        sha256=digest,
                    )

            # Exercise each Nether condition independently.
            nether_filters = (
                FilterConfig(
                    village=False,
                    shipwreck=False,
                    desert_temple=False,
                    ruined_portal=False,
                    buried_treasure=False,
                    stables=True,
                    treasure=False,
                    bridge=False,
                    housing=False,
                    fortress=False,
                ),
                FilterConfig(
                    village=False,
                    shipwreck=False,
                    desert_temple=False,
                    ruined_portal=False,
                    buried_treasure=False,
                    stables=False,
                    treasure=True,
                    bridge=False,
                    housing=False,
                    fortress=False,
                ),
                FilterConfig(
                    village=False,
                    shipwreck=False,
                    desert_temple=False,
                    ruined_portal=False,
                    buried_treasure=False,
                    stables=False,
                    treasure=False,
                    bridge=True,
                    housing=False,
                    fortress=False,
                ),
                FilterConfig(
                    village=False,
                    shipwreck=False,
                    desert_temple=False,
                    ruined_portal=False,
                    buried_treasure=False,
                    stables=False,
                    treasure=False,
                    bridge=False,
                    housing=True,
                    fortress=False,
                ),
                FilterConfig(
                    village=False,
                    shipwreck=False,
                    desert_temple=False,
                    ruined_portal=False,
                    buried_treasure=False,
                    stables=False,
                    treasure=False,
                    bridge=False,
                    housing=False,
                    fortress=True,
                ),
            )

            for structure_filters in nether_filters:
                report = self._check(
                    0,
                    "nether",
                    structure_filters,
                )

                if (
                    report.get("version")
                    != MINECRAFT_VERSION
                    or report.get("seed") != 0
                ):
                    return ProviderSelfTest(
                        False,
                        self.name,
                        BACKEND_PROGRAM_VERSION,
                        "Nether structure lookup failed.",
                        sha256=digest,
                    )

            self._verified = True

            return ProviderSelfTest(
                True,
                self.name,
                BACKEND_PROGRAM_VERSION,
                "MCSeedFinder structure interface passed for "
                "the explicitly configured Minecraft 26.2 target.",
                sha256=digest,
            )

        except (
            OSError,
            ValueError,
            KeyError,
            GenerationUnavailableError,
            subprocess.TimeoutExpired,
        ) as exc:
            return ProviderSelfTest(
                False,
                self.name,
                "",
                f"Provider self-test failed: {exc}",
            )

    @staticmethod
    def _piece_condition(
        piece: str,
    ) -> dict[str, Any]:
        return {
            "type": "structure_piece_near",
            "structure": "bastion_remnant",
            "any_of": [piece],
            "anchor": "nether_spawn",
            "radius": 224,
            "min_count": 1,
        }

    @staticmethod
    def _bastion_condition() -> dict[str, Any]:
        return {
            "type": "structure_near",
            "any_of": ["bastion_remnant"],
            "anchor": "nether_spawn",
            "radius": 224,
            "min_count": 1,
        }

    def _check(
        self,
        seed: int,
        pool: str,
        filters: FilterConfig,
    ) -> dict[str, Any]:

        if pool == "overworld":
            selected: list[dict[str, Any]] = []

            mapping = (
                ("village", "village", 112),
                ("shipwreck", "shipwreck", 64),
                ("desert_temple", "desert_pyramid", 80),
                ("ruined_portal", "ruined_portal", 48),
                ("buried_treasure", "buried_treasure", 80),
            )

            for app_name, backend_name, radius in mapping:
                if getattr(filters, app_name):
                    selected.append(
                        {
                            "type": "structure_near",
                            "any_of": [backend_name],
                            "radius": radius,
                            "anchor": "spawn",
                        }
                    )

        elif pool == "nether":
            selected = []

            if filters.stables:
                selected.append(
                    self._piece_condition(
                        self.STABLES_PIECE
                    )
                )

            if filters.treasure:
                selected.append(
                    self._piece_condition(
                        self.TREASURE_PIECE
                    )
                )

            if filters.bridge:
                selected.append(
                    self._piece_condition(
                        self.BRIDGE_PIECE
                    )
                )

            if filters.housing:
                selected.append(
                    {
                        "type": "all",
                        "conditions": [
                            self._bastion_condition(),
                            {
                                "type": "not",
                                "condition": {
                                    "type": "any",
                                    "conditions": [
                                        self._piece_condition(
                                            self.STABLES_PIECE
                                        ),
                                        self._piece_condition(
                                            self.TREASURE_PIECE
                                        ),
                                        self._piece_condition(
                                            self.BRIDGE_PIECE
                                        ),
                                    ],
                                },
                            },
                        ],
                    }
                )

            if filters.fortress:
                selected.append(
                    {
                        "type": "structure_near",
                        "any_of": ["fortress"],
                        "radius": 256,
                        "anchor": "nether_spawn",
                        "dimension": "nether",
                    }
                )

        else:
            raise GenerationUnavailableError(
                f"Unknown pool: {pool}"
            )

        if not selected:
            raise GenerationUnavailableError(
                f"No {pool} structure filters are enabled."
            )

        config = {
            "version": MINECRAFT_VERSION,
            "conditions": [
                {
                    "type": "any",
                    "conditions": selected,
                }
            ],
        }

        with NamedTemporaryFile(
            "w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(
                config,
                handle,
                ensure_ascii=False,
            )
            config_path = handle.name

        try:
            result = self._run(
                "check",
                str(seed),
                "--config",
                config_path,
                "--format",
                "jsonl",
            )

            if result.returncode not in (0, 1):
                raise GenerationUnavailableError(
                    result.stderr.strip()
                    or "MCSeedFinder rejected the check."
                )

            lines = [
                line
                for line in result.stdout.splitlines()
                if line.strip()
            ]

            if not lines:
                raise GenerationUnavailableError(
                    result.stderr.strip()
                    or "MCSeedFinder returned no check result."
                )

            return json.loads(lines[-1])

        finally:
            try:
                os.unlink(config_path)
            except FileNotFoundError:
                pass

    def accepts(
        self,
        seed: int,
        filters: FilterConfig,
        pool: str = "overworld",
    ) -> bool:
        return bool(
            self.check_seed(
                seed,
                pool,
                filters,
            ).get("matched")
        )

    def check_seed(
        self,
        seed: int,
        pool: str,
        filters: FilterConfig,
    ) -> dict[str, Any]:
        if not self._verified:
            raise GenerationUnavailableError(
                "Provider self-test has not passed."
            )

        return self._check(
            seed,
            pool,
            filters,
        )

    def verify_seed(
        self,
        seed: int,
        pool: str,
        filters: FilterConfig,
    ) -> dict[str, Any]:
        report = self.check_seed(
            seed,
            pool,
            filters,
        )

        report["terrain_check"] = (
            "VERIFIED"
            if self.openTerrainSupported
            else "NOT_AVAILABLE"
        )

        return report

    def get_world_generation_version(self) -> str:
        return MINECRAFT_VERSION

    def find_lava_pool(
        self,
        seed: int,
        pool: str,
    ) -> dict[str, int] | None:
        return None

    def check_open_terrain(
        self,
        seed: int,
        pool: str,
        first: dict[str, Any],
        second: dict[str, Any] | None = None,
    ) -> bool:
        raise GenerationUnavailableError(
            "MCSeedFinder commit "
            "9087c5dc64f2bc12d55609f44ff85fb5b14fc802 "
            "does not expose the required Nether open-terrain/"
            "accessibility query through its public CLI."
        )


def create_provider(
    workdir: Path | None = None,
) -> IMinecraft26WorldGenProvider:
    root = workdir or Path.cwd()

    executable_root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else root
    )

    candidates = [
        executable_root
        / "backend"
        / "mcseed-finder.exe",
        root / "mcseed-finder.exe",
        user_backend_dir()
        / "mcseed-finder.exe",
    ]

    configured = (
        Path(os.environ["MCSEED_FINDER_EXE"])
        if os.environ.get("MCSEED_FINDER_EXE")
        else None
    )

    if configured:
        candidates.append(configured)

    path_backend = (
        shutil.which("mcseed-finder.exe")
        or shutil.which("mcseed-finder")
    )

    if path_backend:
        candidates.append(Path(path_backend))

    seen: set[Path] = set()

    for candidate in candidates:
        candidate = candidate.resolve()

        if candidate in seen:
            continue

        seen.add(candidate)

        if candidate.exists():
            return MCSeedFinderProvider(candidate)

    return UnavailableMinecraft262Provider()
