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

    # ---------------------------------------------------------------
    # Verified 26.2 Bastion subtype pieces.
    # ---------------------------------------------------------------

    STABLES_PIECE = (
        "bastion/hoglin_stable/ramparts/ramparts_3"
    )

    TREASURE_PIECE = (
        "bastion/treasure/ramparts/mid_wall_main"
    )

    BRIDGE_PIECE = (
        "bastion/bridge/starting_pieces/entrance"
    )

    # ---------------------------------------------------------------
    # Verified 26.2 Overworld piece groups.
    # ---------------------------------------------------------------

    VILLAGE_BLACKSMITH_GROUP = "blacksmith"
    SHIPWRECK_FULL_GROUP = "full"

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
            # -------------------------------------------------------
            # Verify executable identity and pinned artifact.
            # -------------------------------------------------------

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

            bastion_pieces = self._run(
                "list",
                "pieces",
                "--structure",
                "bastion_remnant",
            )

            village_pieces = self._run(
                "list",
                "pieces",
                "--structure",
                "village",
            )

            shipwreck_pieces = self._run(
                "list",
                "pieces",
                "--structure",
                "shipwreck",
            )

            buried_pieces = self._run(
                "list",
                "pieces",
                "--structure",
                "buried_treasure",
            )

            ruined_portal_pieces = self._run(
                "list",
                "pieces",
                "--structure",
                "ruined_portal",
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

            try:
                available = json.loads(structures.stdout)
            except json.JSONDecodeError as exc:
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    f"Structure registry JSON was invalid: {exc}",
                    sha256=digest,
                )

            required_structures = {
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

            missing = required_structures - names

            if missing:
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Required 26.2 structure registry entries "
                    f"are missing: {', '.join(sorted(missing))}.",
                    sha256=digest,
                )

            # -------------------------------------------------------
            # Verify Bastion subtype pieces.
            # -------------------------------------------------------

            bastion_text = (
                bastion_pieces.stdout or ""
            ) + (
                bastion_pieces.stderr or ""
            )

            required_bastion_pieces = (
                self.STABLES_PIECE,
                self.TREASURE_PIECE,
                self.BRIDGE_PIECE,
            )

            if any(
                piece not in bastion_text
                for piece in required_bastion_pieces
            ):
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Required 26.2 Bastion subtype pieces "
                    "are missing from the backend.",
                    sha256=digest,
                )

            # -------------------------------------------------------
            # Verify Village blacksmith group.
            # -------------------------------------------------------

            village_text = (
                village_pieces.stdout or ""
            ) + (
                village_pieces.stderr or ""
            )

            if "blacksmith" not in village_text:
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Village blacksmith selector is missing "
                    "from the backend.",
                    sha256=digest,
                )

            # -------------------------------------------------------
            # Verify Shipwreck full group.
            # -------------------------------------------------------

            shipwreck_text = (
                shipwreck_pieces.stdout or ""
            ) + (
                shipwreck_pieces.stderr or ""
            )

            if "full" not in shipwreck_text:
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Shipwreck full selector is missing "
                    "from the backend.",
                    sha256=digest,
                )

            # -------------------------------------------------------
            # Verify Buried Treasure chest is available for
            # reporting. It is NOT used as a filter because the
            # backend rejects `chest` as a selectable group.
            # -------------------------------------------------------

            buried_text = (
                buried_pieces.stdout or ""
            ) + (
                buried_pieces.stderr or ""
            )

            if "buried_treasure/chest" not in buried_text:
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Buried Treasure chest reporting piece "
                    "is missing from the backend.",
                    sha256=digest,
                )

            # -------------------------------------------------------
            # Verify Ruined Portal exposes portal pieces.
            #
            # We deliberately do NOT infer "completable" from these
            # pieces because the backend provides no direct
            # completeness test.
            # -------------------------------------------------------

            portal_text = (
                ruined_portal_pieces.stdout or ""
            ) + (
                ruined_portal_pieces.stderr or ""
            )

            if "ruined_portal/portal_" not in portal_text:
                return ProviderSelfTest(
                    False,
                    self.name,
                    BACKEND_PROGRAM_VERSION,
                    "Ruined Portal portal pieces are missing "
                    "from the backend.",
                    sha256=digest,
                )

            # -------------------------------------------------------
            # Exercise every Overworld filter independently.
            # -------------------------------------------------------

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

            # -------------------------------------------------------
            # Test compound subtype selectors.
            # -------------------------------------------------------

            compound_filters = (
                # Village + blacksmith
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
                # Shipwreck + full ship
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
            )

            for structure_filters in compound_filters:
                report = self._check(
                    0,
                    "overworld",
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
                        "Overworld subtype lookup failed.",
                        sha256=digest,
                    )

            # -------------------------------------------------------
            # Exercise each Nether condition independently.
            # -------------------------------------------------------

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
                "Minecraft Java 26.2, including verified "
                "Overworld and Bastion subtype selectors.",
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

    # ------------------------------------------------------------------
    # Generic Overworld structure condition.
    # ------------------------------------------------------------------

    @staticmethod
    def _overworld_structure_condition(
        structure: str,
        radius: int,
    ) -> dict[str, Any]:
        return {
            "type": "structure_near",
            "any_of": [structure],
            "anchor": "spawn",
            "radius": radius,
            "min_count": 1,
        }

    # ------------------------------------------------------------------
    # Overworld piece condition.
    #
    # Unlike Bastion, these use the Overworld spawn anchor.
    # ------------------------------------------------------------------

    @staticmethod
    def _overworld_piece_condition(
        structure: str,
        piece_group: str,
        radius: int,
    ) -> dict[str, Any]:
        return {
            "type": "structure_piece_near",
            "structure": structure,
            "any_of": [piece_group],
            "anchor": "spawn",
            "radius": radius,
            "min_count": 1,
        }

    # ------------------------------------------------------------------
    # Bastion piece condition.
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Build the actual backend condition tree.
    #
    # IMPORTANT:
    # Each selected filter is an alternative (OR).
    #
    # A selected Village filter means:
    #
    #     village within 112
    #     AND blacksmith within 112
    #
    # A selected Shipwreck filter means:
    #
    #     shipwreck within 64
    #     AND full ship within 64
    #
    # The different selected filters are then combined with ANY.
    # ------------------------------------------------------------------

    def _check(
        self,
        seed: int,
        pool: str,
        filters: FilterConfig,
    ) -> dict[str, Any]:

        if pool == "overworld":
            selected: list[dict[str, Any]] = []

            # -------------------------------------------------------
            # Village + Blacksmith
            #
            # MCSR proximity: village within 7 chunks = 112 blocks.
            # The backend supports a direct `blacksmith` group.
            # -------------------------------------------------------

            if filters.village:
                selected.append(
                    {
                        "type": "all",
                        "conditions": [
                            self._overworld_structure_condition(
                                "village",
                                112,
                            ),
                            self._overworld_piece_condition(
                                "village",
                                self.VILLAGE_BLACKSMITH_GROUP,
                                112,
                            ),
                        ],
                    }
                )

            # -------------------------------------------------------
            # Shipwreck + Full Ship
            #
            # MCSR proximity: shipwreck within 4 chunks = 64 blocks.
            # The backend's `full` group excludes degraded pieces.
            # -------------------------------------------------------

            if filters.shipwreck:
                selected.append(
                    {
                        "type": "all",
                        "conditions": [
                            self._overworld_structure_condition(
                                "shipwreck",
                                64,
                            ),
                            self._overworld_piece_condition(
                                "shipwreck",
                                self.SHIPWRECK_FULL_GROUP,
                                64,
                            ),
                        ],
                    }
                )

            # -------------------------------------------------------
            # Desert Temple
            #
            # MCSR proximity: 5 chunks = 80 blocks.
            # -------------------------------------------------------

            if filters.desert_temple:
                selected.append(
                    self._overworld_structure_condition(
                        "desert_pyramid",
                        80,
                    )
                )

            # -------------------------------------------------------
            # Ruined Portal
            #
            # MCSR proximity: 3 chunks = 48 blocks.
            #
            # IMPORTANT:
            # The backend does not expose a reliable "completable"
            # selector. We therefore do NOT falsely require one.
            # -------------------------------------------------------

            if filters.ruined_portal:
                selected.append(
                    self._overworld_structure_condition(
                        "ruined_portal",
                        48,
                    )
                )

            # -------------------------------------------------------
            # Buried Treasure
            #
            # MCSR proximity: 5 chunks = 80 blocks.
            #
            # The backend exposes buried_treasure/chest for reporting,
            # but rejects `chest` as a selectable structure_piece_near
            # group. Therefore the filter is the actual structure.
            # -------------------------------------------------------

            if filters.buried_treasure:
                selected.append(
                    self._overworld_structure_condition(
                        "buried_treasure",
                        80,
                    )
                )

        elif pool == "nether":
            selected = []

            # -------------------------------------------------------
            # Bastion Stables
            # -------------------------------------------------------

            if filters.stables:
                selected.append(
                    self._piece_condition(
                        self.STABLES_PIECE
                    )
                )

            # -------------------------------------------------------
            # Bastion Treasure
            # -------------------------------------------------------

            if filters.treasure:
                selected.append(
                    self._piece_condition(
                        self.TREASURE_PIECE
                    )
                )

            # -------------------------------------------------------
            # Bastion Bridge
            # -------------------------------------------------------

            if filters.bridge:
                selected.append(
                    self._piece_condition(
                        self.BRIDGE_PIECE
                    )
                )

            # -------------------------------------------------------
            # Bastion Housing
            #
            # The pinned backend does not expose a stable Housing
            # selector. We therefore use the documented application
            # heuristic:
            #
            #   generic bastion exists
            #   AND none of the three exposed subtype markers exist.
            #
            # This must not be described as a direct backend Housing
            # piece check.
            # -------------------------------------------------------

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

            # -------------------------------------------------------
            # Fortress
            #
            # MCSR proximity: 16 chunks = 256 blocks.
            # -------------------------------------------------------

            if filters.fortress:
                selected.append(
                    {
                        "type": "structure_near",
                        "any_of": ["fortress"],
                        "radius": 256,
                        "anchor": "nether_spawn",
                        "dimension": "nether",
                        "min_count": 1,
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

        # -----------------------------------------------------------
        # Multiple selected filters are OR alternatives.
        #
        # Example:
        #
        #   Village selected
        #   Shipwreck selected
        #
        # means:
        #
        #   (Village + Blacksmith)
        #       OR
        #   (Shipwreck + Full Ship)
        #
        # A seed can satisfy more than one child, and MCSeedFinder's
        # JSON report preserves all matched children/hits.
        # -----------------------------------------------------------

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

            # MCSeedFinder:
            #
            # 0 = matched
            # 1 = valid seed but no match
            # 2+ = error
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

            try:
                return json.loads(lines[-1])
            except json.JSONDecodeError as exc:
                raise GenerationUnavailableError(
                    "MCSeedFinder returned invalid JSON: "
                    f"{exc}"
                ) from exc

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