from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .cache import MAX_SEED, MIN_SEED, SeedCache
from .config import AppConfig
from .engine import GenerationUnavailableError, WorldGenerationProvider


@dataclass
class Progress:
    target: int = 0
    found: int = 0
    candidates: int = 0
    rejected: int = 0
    duplicates: int = 0
    started_at: float = 0.0
    finished: bool = False
    error: str | None = None


class CandidateStream:
    def __init__(self, master_seed: int | None = None):
        self.random = (
            random.Random(master_seed)
            if master_seed is not None
            else random.SystemRandom()
        )

        self._lock = threading.Lock()
        self._seen: set[int] = set()

    def next(self) -> int:
        with self._lock:
            while True:
                value = self.random.randint(
                    MIN_SEED,
                    MAX_SEED,
                )

                if value not in self._seen:
                    self._seen.add(value)
                    return value


class GenerationController:
    def __init__(
        self,
        config: AppConfig,
        cache: SeedCache,
        provider: WorldGenerationProvider,
        state_path: Path,
        logger: logging.Logger,
        on_progress: Callable[[Progress], None] | None = None,
        target: int | None = None,
        pool: str = "overworld",
    ):
        self.config = config
        self.cache = cache
        self.provider = provider
        self.pool = pool
        self.state_path = state_path
        self.logger = logger
        self.on_progress = on_progress

        self.progress = Progress(
            target=(
                config.target_seeds
                if target is None
                else target
            ),
            started_at=time.monotonic(),
        )

        self.pause_event = threading.Event()
        self.stop_event = threading.Event()

        self.pause_event.set()
        self._progress_lock = threading.Lock()

        self._candidate_stream = CandidateStream(
            config.master_rng_seed
        )

    def pause(self) -> None:
        self.pause_event.clear()

    def resume(self) -> None:
        self.pause_event.set()

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.set()

    def run(self) -> Progress:
        if self.progress.target == 0:
            self.progress.finished = True
            return self.progress

        native_batch = (
            getattr(self.provider, "find_batch", None) is not None
            and self.pool in ("overworld", "nether")
        )

        workers = (
            1
            if native_batch
            else (
                self.config.workers
                or max(
                    1,
                    (os.cpu_count() or 2) - 1,
                )
            )
        )

        self.logger.info(
            "generation start version=%s filter=%s target=%s workers=%s",
            self.config.minecraft_version,
            self.config.filter_version,
            self.progress.target,
            workers,
        )

        threads = [
            threading.Thread(
                target=self._worker,
                name=f"seed-worker-{i}",
                daemon=True,
            )
            for i in range(workers)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        self.progress.finished = True
        self._checkpoint()

        self.cache.export(
            self.progress.found
        )

        self.logger.info(
            "generation complete found=%s candidates=%s",
            self.progress.found,
            self.progress.candidates,
        )

        return self.progress

    def _worker(self) -> None:
        finder = getattr(self.provider, "find_batch", None)

        # Native MCSeedFinder batch path.
        if finder is not None and self.pool in ("overworld", "nether"):
            native_threads = max(
                1,
                self.config.workers or 8,
            )
            batch_size = 1000
            rng = random.SystemRandom()

            while not self.stop_event.is_set():
                self.pause_event.wait()

                with self._progress_lock:
                    remaining = (
                        self.progress.target
                        - self.progress.found
                    )

                if remaining <= 0:
                    self.stop_event.set()
                    return

                count = min(batch_size, remaining)

                try:
                    reports = finder(
                        self.pool,
                        self.config.filters,
                        count,
                        rng.randrange(0, 2**64),
                        native_threads,
                    )
                except GenerationUnavailableError as exc:
                    self.progress.error = str(exc)
                    self.stop_event.set()
                    return
                except Exception as exc:
                    self.progress.error = str(exc)
                    self.logger.exception(
                        "native batch generation failed"
                    )
                    self.stop_event.set()
                    return

                inserted_count = 0

                for report in reports:
                    if self.stop_event.is_set():
                        return

                    self.pause_event.wait()

                    seed_value = report.get("seed")
                    if seed_value is None:
                        continue

                    try:
                        candidate = int(seed_value)
                    except (TypeError, ValueError):
                        continue

                    labels = extract_structure_labels(report)

                    with self._progress_lock:
                        if self.progress.found >= self.progress.target:
                            self.stop_event.set()
                            return

                        inserted = self.cache.insert(
                            str(candidate),
                            labels,
                        )

                        if not inserted:
                            self.progress.duplicates += 1
                            continue

                        self.progress.found += 1
                        self.progress.candidates += 1
                        inserted_count += 1

                    if self.on_progress:
                        self.on_progress(self.progress)

                if inserted_count:
                    self._checkpoint()

            return

        # Legacy per-seed fallback.
        while not self.stop_event.is_set():
            self.pause_event.wait()

            with self._progress_lock:
                if self.progress.found >= self.progress.target:
                    self.stop_event.set()
                    return

            candidate = self._candidate_stream.next()

            with self._progress_lock:
                self.progress.candidates += 1

            try:
                checker = getattr(self.provider, "check_seed", None)
                report = (
                    checker(
                        candidate,
                        self.pool,
                        self.config.filters,
                    )
                    if checker
                    else None
                )
                accepted = (
                    bool(report.get("matched"))
                    if report is not None
                    else self.provider.accepts(
                        candidate,
                        self.config.filters,
                        self.pool,
                    )
                )
            except GenerationUnavailableError as exc:
                self.progress.error = str(exc)
                self.stop_event.set()
                return

            if not accepted:
                with self._progress_lock:
                    self.progress.rejected += 1
                continue

            with self._progress_lock:
                if self.progress.found >= self.progress.target:
                    self.stop_event.set()
                    return

                labels = (
                    extract_structure_labels(report)
                    if report is not None
                    else ()
                )

                inserted = self.cache.insert(
                    str(candidate),
                    labels,
                )

                if not inserted:
                    self.progress.duplicates += 1
                    continue

                self.progress.found += 1

            self._checkpoint()

            if self.on_progress:
                self.on_progress(self.progress)

    def _checkpoint(self) -> None:
        self.state_path.write_text(
            json.dumps(
                self.progress.__dict__,
                indent=2,
            ),
            encoding="utf-8",
        )


def extract_structure_labels(
    report: dict | None,
) -> tuple[str, ...]:
    if not report:
        return ()

    labels: list[str] = []

    def add(label: str) -> None:
        if label not in labels:
            labels.append(label)

    direct_bastion = False
    subtype_hit = False

    def visit(value: object) -> None:
        nonlocal direct_bastion
        nonlocal subtype_hit

        if not isinstance(value, dict):
            return

        condition = value.get("condition")

        if condition in (
            "structure_near",
            "structure_piece_near",
        ):
            if value.get("matched"):
                for hit in value.get("hits", []):
                    if not isinstance(hit, dict):
                        continue

                    name = str(
                        hit.get("name", "")
                    )

                    if name == "desert_pyramid":
                        add("Desert Temple")

                    elif name == "ruined_portal":
                        add("Ruined Portal")

                    elif name == "buried_treasure":
                        add("Buried Treasure")

                    elif name == "village":
                        add("Village")

                    elif name == "shipwreck":
                        add("Shipwreck")

                    elif name == "fortress":
                        add("Fortress")

                    elif (
                        name
                        == "bastion_remnant"
                    ):
                        direct_bastion = True

                    elif name.startswith(
                        "bastion/bridge/"
                    ):
                        subtype_hit = True
                        add("Bridge")

                    elif name.startswith(
                        "bastion/hoglin_stable/"
                    ):
                        subtype_hit = True
                        add("Stables")

                    elif name.startswith(
                        "bastion/treasure/"
                    ):
                        subtype_hit = True
                        add("Treasure")

        for child in value.get(
            "children",
            [],
        ):
            visit(child)

    visit(report.get("filter"))

    # Residual Housing rule:
    #
    # A backend-reported Bastion exists, but no supported
    # Stables, Treasure, or Bridge piece was reported.
    #
    # This is intentionally an application-level derived
    # classification, not a claim that MCSeedFinder exposed
    # a dedicated Housing piece.
    if direct_bastion and not subtype_hit:
        add("Housing")

    return tuple(labels)
