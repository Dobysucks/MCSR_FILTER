from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MINECRAFT_VERSION = "26.2"
DEFAULT_FILTER_VERSION = "MCSR-26.2-ADAPTED-v4"
PRODUCTION_TARGET = 500000

FILTER_NAMES = (
    "village",
    "shipwreck",
    "desert_temple",
    "ruined_portal",
    "buried_treasure",
    "stables",
    "treasure",
    "bridge",
    "housing",
    "fortress",
)


@dataclass
class FilterConfig:
    village: bool = True
    shipwreck: bool = True
    desert_temple: bool = True
    ruined_portal: bool = True
    buried_treasure: bool = True

    stables: bool = True
    treasure: bool = True
    bridge: bool = True
    housing: bool = True
    fortress: bool = True


@dataclass
class AppConfig:
    minecraft_version: str = MINECRAFT_VERSION
    filter_version: str = DEFAULT_FILTER_VERSION
    target_seeds: int = PRODUCTION_TARGET
    target_overworld: int = PRODUCTION_TARGET
    target_nether: int = PRODUCTION_TARGET
    workers: int = 0
    master_rng_seed: int | None = None
    filters: FilterConfig = field(default_factory=FilterConfig)

    def validate(self) -> None:
        if self.minecraft_version != MINECRAFT_VERSION:
            raise ValueError("Only Minecraft Java 26.2 is supported.")

        if not self.filter_version:
            raise ValueError("filter_version must not be empty.")

        if self.target_seeds < 0:
            raise ValueError("target_seeds must be non-negative.")

        if self.target_overworld < 0 or self.target_nether < 0:
            raise ValueError("pool targets must be non-negative.")

        if self.workers < 0:
            raise ValueError("workers must be non-negative.")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "AppConfig":
        filters = raw.get("filters") or {}

        # Preserve old config files. The old generic "bastion" option
        # is migrated to all four new Bastion categories.
        old_bastion = bool(filters.get("bastion", True))

        result = cls(
            minecraft_version=str(
                raw.get(
                    "minecraft_version",
                    MINECRAFT_VERSION,
                )
            ),
            filter_version=str(
                raw.get(
                    "filter_version",
                    DEFAULT_FILTER_VERSION,
                )
            ),
            target_seeds=int(
                raw.get(
                    "target_seeds",
                    PRODUCTION_TARGET,
                )
            ),
            target_overworld=int(
                raw.get(
                    "target_overworld",
                    raw.get(
                        "target_seeds",
                        PRODUCTION_TARGET,
                    ),
                )
            ),
            target_nether=int(
                raw.get(
                    "target_nether",
                    raw.get(
                        "target_seeds",
                        PRODUCTION_TARGET,
                    ),
                )
            ),
            workers=int(raw.get("workers", 0)),
            master_rng_seed=raw.get("master_rng_seed"),
            filters=FilterConfig(
                village=bool(filters.get("village", True)),
                shipwreck=bool(filters.get("shipwreck", True)),
                desert_temple=bool(
                    filters.get("desert_temple", True)
                ),
                ruined_portal=bool(
                    filters.get("ruined_portal", True)
                ),
                buried_treasure=bool(
                    filters.get("buried_treasure", True)
                ),
                stables=bool(
                    filters.get("stables", old_bastion)
                ),
                treasure=bool(
                    filters.get("treasure", old_bastion)
                ),
                bridge=bool(
                    filters.get("bridge", old_bastion)
                ),
                housing=bool(
                    filters.get("housing", old_bastion)
                ),
                fortress=bool(
                    filters.get("fortress", True)
                ),
            ),
        )

        result.validate()
        return result

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        config = AppConfig()
        save_config(path, config)
        return config

    with path.open("r", encoding="utf-8") as handle:
        return AppConfig.from_mapping(
            json.load(handle)
        )


def save_config(
    path: Path,
    config: AppConfig,
) -> None:
    config.validate()

    path.write_text(
        json.dumps(
            config.to_mapping(),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
