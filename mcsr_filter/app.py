from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .backend import BackendInstallError, BackendInstaller
from .cache import SeedCache
from .config import (
    FILTER_NAMES,
    PRODUCTION_TARGET,
    AppConfig,
    FilterConfig,
    load_config,
    save_config,
)
from .engine import GenerationUnavailableError, create_provider
from .generator import GenerationController, Progress
from .logging_setup import configure_logging


FILTER_LABELS = {
    "village": "Village",
    "shipwreck": "Shipwreck",
    "desert_temple": "Desert Temple",
    "ruined_portal": "Ruined Portal",
    "buried_treasure": "Buried Treasure",
    "stables": "Stables",
    "treasure": "Treasure",
    "bridge": "Bridge",
    "housing": "Housing",
    "fortress": "Fortress",
}


class App:
    def __init__(
        self,
        root: tk.Tk,
        workdir: Path,
    ):
        self.root = root
        self.workdir = workdir
        self.config_path = workdir / "config.json"
        self.config = load_config(self.config_path)

        database = workdir / "mcsr_26_2_seed_cache.db"

        self.overworld_cache = SeedCache(
            database,
            workdir / "overworld_seeds.txt",
            self.config.minecraft_version,
            self.config.filter_version,
            "overworld",
        )

        self.nether_cache = SeedCache(
            database,
            workdir / "nether_seeds.txt",
            self.config.minecraft_version,
            self.config.filter_version,
            "nether",
        )

        self.logger = configure_logging(
            workdir / "logs" / "generation.log"
        )

        self.provider = create_provider(workdir)
        self.backend_installer = BackendInstaller()
        self.provider_test = self.provider.self_test()

        self.test_passed = False
        self.test_running = False

        self.controller: GenerationController | None = None
        self.thread: threading.Thread | None = None

        self.target = tk.StringVar(
            value=str(self.config.target_overworld)
        )

        self.nether_target = tk.StringVar(
            value=str(self.config.target_nether)
        )

        self.workers = tk.StringVar(
            value=str(self.config.workers)
        )

        self.status = tk.StringVar(
            value=self.provider_test.message
        )

        self.labels: dict[str, tk.StringVar] = {
            name: tk.StringVar(value="")
            for name in (
                "cached",
                "found",
                "tested",
                "speed",
            )
        }

        self.filter_vars = {
            name: tk.BooleanVar(
                value=getattr(
                    self.config.filters,
                    name,
                )
            )
            for name in FILTER_NAMES
        }

        self.engine_status_label: ttk.Label | None = None
        self.provider_status_label: ttk.Label | None = None
        self.test_button: ttk.Button | None = None

        self._build()
        self._refresh()

    def _backend_status(self) -> str:
        if self.provider_test.verified:
            return "INSTALLED / VERIFIED"

        return self.backend_installer.status()

    def _build(self) -> None:
        self.root.title(
            "MCSR 26.2 Seed Filter"
        )
        self.root.geometry(
            "820x650"
        )

        frame = ttk.Frame(
            self.root,
            padding=16,
        )

        frame.pack(
            fill="both",
            expand=True,
        )

        ttk.Label(
            frame,
            text="Minecraft Version: 26.2",
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        self.engine_status_label = ttk.Label(
            frame,
            text=f"Seed Engine: {self._backend_status()}",
        )

        self.engine_status_label.grid(
            row=0,
            column=1,
            sticky="w",
        )

        self.provider_status_label = ttk.Label(
            frame,
            text=(
                f"Provider: {self.provider_test.provider_name} "
                f"({'VERIFIED' if self.provider_test.verified else 'NOT VERIFIED'})"
            ),
        )

        self.provider_status_label.grid(
            row=0,
            column=2,
            sticky="w",
        )

        ttk.Label(
            frame,
            text=f"Filter: {self.config.filter_version}",
        ).grid(
            row=0,
            column=3,
            sticky="w",
        )

        ttk.Label(
            frame,
            text=(
                "Optional: Loot NOT REQUIRED | Lava Pool NOT REQUIRED | "
                f"Open Terrain "
                f"{'AVAILABLE' if getattr(self.provider, 'openTerrainSupported', False) else 'NOT AVAILABLE'}"
            ),
        ).grid(
            row=17,
            column=0,
            columnspan=4,
            sticky="w",
        )

        ttk.Label(
            frame,
            text="New overworld seeds:",
        ).grid(
            row=1,
            column=0,
            sticky="w",
        )

        ttk.Entry(
            frame,
            textvariable=self.target,
            width=14,
        ).grid(
            row=1,
            column=1,
            sticky="w",
        )

        ttk.Label(
            frame,
            text="New nether seeds:",
        ).grid(
            row=2,
            column=0,
            sticky="w",
        )

        ttk.Entry(
            frame,
            textvariable=self.nether_target,
            width=14,
        ).grid(
            row=2,
            column=1,
            sticky="w",
        )

        ttk.Label(
            frame,
            text="Worker threads (0 = auto):",
        ).grid(
            row=3,
            column=0,
            sticky="w",
        )

        ttk.Entry(
            frame,
            textvariable=self.workers,
            width=14,
        ).grid(
            row=3,
            column=1,
            sticky="w",
        )

        ttk.Label(
            frame,
            text="Filters (ANY selected type qualifies):",
        ).grid(
            row=4,
            column=0,
            sticky="w",
            pady=(14, 0),
        )

        overworld_names = (
            "village",
            "shipwreck",
            "desert_temple",
            "ruined_portal",
            "buried_treasure",
        )

        nether_names = (
            "stables",
            "treasure",
            "bridge",
            "housing",
            "fortress",
        )

        ttk.Label(
            frame,
            text="Overworld",
        ).grid(
            row=5,
            column=0,
            sticky="w",
        )

        for index, name in enumerate(
            overworld_names,
            start=6,
        ):
            ttk.Checkbutton(
                frame,
                text=FILTER_LABELS[name],
                variable=self.filter_vars[name],
            ).grid(
                row=index,
                column=0,
                sticky="w",
            )

        ttk.Label(
            frame,
            text="Nether",
        ).grid(
            row=5,
            column=1,
            sticky="w",
        )

        for index, name in enumerate(
            nether_names,
            start=6,
        ):
            checkbutton = ttk.Checkbutton(
                frame,
                text=FILTER_LABELS[name],
                variable=self.filter_vars[name],
            )

            checkbutton.grid(
                row=index,
                column=1,
                sticky="w",
            )

        ttk.Label(
            frame,
            text=(
                "Housing = Bastion found, but no supported "
                "Stables / Treasure / Bridge piece found."
            ),
            wraplength=360,
        ).grid(
            row=11,
            column=1,
            sticky="w",
            pady=(6, 0),
        )

        buttons = ttk.Frame(frame)

        buttons.grid(
            row=6,
            column=2,
            rowspan=7,
            sticky="n",
            padx=30,
        )

        ttk.Button(
            buttons,
            text="START OVERWORLD",
            command=self.start_overworld,
        ).pack(fill="x")

        ttk.Button(
            buttons,
            text="START NETHER",
            command=self.start_nether,
        ).pack(
            fill="x",
            pady=4,
        )

        ttk.Button(
            buttons,
            text="VERIFY PROVIDER",
            command=self.verify_provider,
        ).pack(
            fill="x",
            pady=4,
        )

        ttk.Button(
            buttons,
            text="INSTALL 26.2 SEED ENGINE",
            command=self.install_backend,
        ).pack(fill="x")

        self.test_button = ttk.Button(
            buttons,
            text="TEST 100 + 100",
            command=self.test_mode,
        )

        self.test_button.pack(
            fill="x",
        )

        ttk.Button(
            buttons,
            text="PAUSE",
            command=self.pause,
        ).pack(
            fill="x",
            pady=4,
        )

        ttk.Button(
            buttons,
            text="RESUME",
            command=self.resume,
        ).pack(fill="x")

        ttk.Button(
            buttons,
            text="STOP",
            command=self.stop,
        ).pack(
            fill="x",
            pady=4,
        )

        ttk.Button(
            buttons,
            text="EXPORT TXT",
            command=self.export,
        ).pack(fill="x")

        ttk.Button(
            buttons,
            text="VERIFY SEEDS",
            command=self.verify_seeds,
        ).pack(fill="x")

        ttk.Button(
            buttons,
            text="OPEN OUTPUT FOLDER",
            command=lambda: os.startfile(
                self.workdir
            ),
        ).pack(
            fill="x",
            pady=4,
        )

        stats = ttk.LabelFrame(
            frame,
            text="Progress",
            padding=10,
        )

        stats.grid(
            row=13,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(20, 0),
        )

        for row, (label, key) in enumerate(
            (
                (
                    "Cached overworld / nether",
                    "cached",
                ),
                (
                    "New overworld / nether",
                    "found",
                ),
                (
                    "Candidates tested",
                    "tested",
                ),
                (
                    "Current speed",
                    "speed",
                ),
            )
        ):
            ttk.Label(
                stats,
                text=label + ":",
            ).grid(
                row=row,
                column=0,
                sticky="w",
            )

            ttk.Label(
                stats,
                textvariable=self.labels[key],
            ).grid(
                row=row,
                column=1,
                sticky="w",
            )

        ttk.Label(
            frame,
            textvariable=self.status,
            wraplength=780,
        ).grid(
            row=14,
            column=0,
            columnspan=3,
            sticky="w",
            pady=16,
        )

    def _update_engine_status(self) -> None:
        if self.engine_status_label is not None:
            self.engine_status_label.config(
                text=f"Seed Engine: {self._backend_status()}"
            )

        if self.provider_status_label is not None:
            self.provider_status_label.config(
                text=(
                    f"Provider: {self.provider_test.provider_name} "
                    f"({'VERIFIED' if self.provider_test.verified else 'NOT VERIFIED'})"
                )
            )

    def _read_config(self) -> AppConfig:
        config = AppConfig.from_mapping(
            {
                "minecraft_version": "26.2",
                "filter_version": self.config.filter_version,
                "target_seeds": int(
                    self.target.get()
                ),
                "target_overworld": int(
                    self.target.get()
                ),
                "target_nether": int(
                    self.nether_target.get()
                ),
                "workers": int(
                    self.workers.get()
                ),
                "filters": {
                    name: self.filter_vars[name].get()
                    for name in FILTER_NAMES
                },
            }
        )

        save_config(
            self.config_path,
            config,
        )

        return config

    def _start_pool(self, pool: str) -> None:
        if self.test_running:
            self.status.set(
                "TEST 100 + 100 is still running. "
                "Generation is temporarily disabled."
            )
            return

        try:
            self.config = self._read_config()
        except (ValueError, TypeError) as exc:
            messagebox.showerror(
                "Invalid configuration",
                str(exc),
            )
            return

        if (
            not self.provider_test.verified
            or not self.test_passed
        ):
            if not self.provider_test.verified:
                self.install_backend()

            self.status.set(
                "Minecraft 26.2 world-generation provider "
                "verification failed. Seed generation has been "
                "disabled to prevent inaccurate results."
            )
            return

        if pool == "overworld":
            target = self.config.target_overworld
            cache = self.overworld_cache
            state_path = self.workdir / "overworld_generation_state.json"
        else:
            target = self.config.target_nether
            cache = self.nether_cache
            state_path = self.workdir / "nether_generation_state.json"

        controller = GenerationController(
            self.config,
            cache,
            self.provider,
            state_path,
            self.logger,
            lambda p: self._on_progress(p, pool),
            target,
            pool,
        )

        self.controllers = [controller]
        self.controller = controller

        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )
        self.thread.start()

        self.status.set(
            f"Running verified {pool} generation."
        )

    def start_overworld(self) -> None:
        self._start_pool("overworld")

    def start_nether(self) -> None:
        self._start_pool("nether")

    def start(self) -> None:
        # Backward-compatible alias for older callers.
        self.start_nether()


    def install_backend(self) -> None:
        try:
            path = self.backend_installer.install()

        except BackendInstallError as exc:
            self._update_engine_status()

            messagebox.showerror(
                "Minecraft 26.2 Seed Engine Required",
                str(exc),
            )

            self.status.set(str(exc))
            return

        self.provider = create_provider(
            self.workdir
        )

        self.provider_test = (
            self.provider.self_test()
        )

        self._update_engine_status()

        self.status.set(
            f"Installed {path}; "
            f"{self.provider_test.message}"
        )

    def verify_provider(self) -> None:
        if self.test_running:
            self.status.set(
                "Provider verification is unavailable "
                "while TEST is running."
            )
            return

        self.provider = create_provider(
            self.workdir
        )

        self.provider_test = (
            self.provider.self_test()
        )

        self._update_engine_status()

        self.status.set(
            self.provider_test.message
        )

    def test_mode(self) -> None:
        if not self.provider_test.verified:
            self.status.set(
                "TEST 100 + 100 blocked: provider is not verified."
            )
            return

        if self.test_running:
            self.status.set(
                "TEST 100 + 100 is already running."
            )
            return

        if (
            self.thread is not None
            and self.thread.is_alive()
        ):
            self.status.set(
                "Generation is already running."
            )
            return

        self.test_running = True
        self.test_passed = False

        if self.test_button is not None:
            self.test_button.config(
                state="disabled"
            )

        self.status.set(
            "TEST 100 + 100 running; "
            "optional open terrain is skipped."
        )

        threading.Thread(
            target=self._run_test_mode,
            daemon=True,
        ).start()

    def _run_test_mode(self) -> None:
        try:
            import tempfile

            with tempfile.TemporaryDirectory(prefix="mcsr26_test_") as test_dir:
                test_path = Path(test_dir)

                results: dict[str, list[set[str]]] = {}

                for pool, label in (
                    ("overworld", "Overworld"),
                    ("nether", "Nether"),
                ):
                    test_cache = SeedCache(
                        Path(":memory:"),
                        test_path / f"{pool}_seeds.txt",
                        self.config.minecraft_version,
                        self.config.filter_version,
                        pool,
                    )

                    previous: set[str] = set()
                    batches: list[set[str]] = []

                    for round_number in (1, 2):
                        test_filters = FilterConfig(
                            village=(pool == "overworld"),
                            shipwreck=False,
                            desert_temple=False,
                            ruined_portal=False,
                            buried_treasure=False,
                            stables=(pool == "nether"),
                            treasure=(pool == "nether"),
                            bridge=(pool == "nether"),
                            housing=(pool == "nether"),
                            fortress=(pool == "nether"),
                        )
                        config = AppConfig.from_mapping({
                            **self.config.to_mapping(),
                            "target_overworld": 100 if pool == "overworld" else 0,
                            "target_nether": 100 if pool == "nether" else 0,
                            "target_seeds": 100,
                            "filters": {
                                "village": test_filters.village,
                                "shipwreck": test_filters.shipwreck,
                                "desert_temple": test_filters.desert_temple,
                                "ruined_portal": test_filters.ruined_portal,
                                "buried_treasure": test_filters.buried_treasure,
                                "stables": test_filters.stables,
                                "treasure": test_filters.treasure,
                                "bridge": test_filters.bridge,
                                "housing": test_filters.housing,
                                "fortress": test_filters.fortress,
                            },
                        })

                        controller = GenerationController(
                            config,
                            test_cache,
                            self.provider,
                            test_path / f"test_{pool}_{round_number}.json",
                            self.logger,
                            target=100,
                            pool=pool,
                        )

                        worker = threading.Thread(
                            target=controller.run,
                            daemon=True,
                        )
                        worker.start()
                        worker.join()

                        current = (
                            set(test_cache.seeds())
                            - previous
                        )

                        if len(current) != 100:
                            test_cache.close()
                            self.root.after(
                                0,
                                lambda l=label, r=round_number:
                                self._finish_test(
                                    False,
                                    (
                                        f"TEST 100 {l} round {r} failed; "
                                        "production remains disabled."
                                    ),
                                ),
                            )
                            return

                        try:
                            for seed in current:
                                self.provider.verify_seed(
                                    int(seed),
                                    pool,
                                    test_filters,
                                )
                        except (
                            GenerationUnavailableError,
                            ValueError,
                        ):
                            test_cache.close()
                            self.root.after(
                                0,
                                lambda l=label:
                                self._finish_test(
                                    False,
                                    (
                                        f"TEST {l} verification failed; "
                                        "production remains disabled."
                                    ),
                                ),
                            )
                            return

                        batches.append(current)
                        previous |= current

                    test_cache.close()
                    results[pool] = batches

                overworld_passed = not results["overworld"][0].intersection(
                    results["overworld"][1]
                )
                nether_passed = not results["nether"][0].intersection(
                    results["nether"][1]
                )
                test_passed = overworld_passed and nether_passed

                self.root.after(
                    0,
                    lambda: self._finish_test(
                        test_passed,
                        (
                            "TEST 100 Overworld + 100 Nether passed twice; "
                            "production generation is enabled."
                            if test_passed
                            else
                            "TEST duplicate check failed; "
                            "production remains disabled."
                        ),
                    ),
                )

        except Exception as exc:
            self.logger.exception(
                "TEST 100 Overworld + 100 Nether failed unexpectedly"
            )
            error_message = str(exc)
            self.root.after(
                0,
                lambda message=error_message: self._finish_test(
                    False,
                    f"TEST failed unexpectedly: {message}",
                ),
            )

    def _finish_test(
        self,
        passed: bool,
        message: str,
    ) -> None:
        self.test_passed = passed
        self.test_running = False

        if self.test_button is not None:
            self.test_button.config(
                state="normal"
            )

        self.status.set(message)

    def verify_seeds(self) -> None:
        report_path = (
            self.workdir / "validation_report.txt"
        )

        lines = [
            f"Provider: {self.provider_test.provider_name}",
            f"Provider version: {self.provider_test.version}",
            f"Filter version: {self.config.filter_version}",
        ]

        for pool, cache in (
            ("overworld", self.overworld_cache),
            ("nether", self.nether_cache),
        ):
            seeds = cache.seeds()
            valid = 0
            invalid = 0

            for seed in seeds:
                try:
                    self.provider.verify_seed(
                        int(seed),
                        pool,
                        self.config.filters,
                    )
                    valid += 1

                except (
                    GenerationUnavailableError,
                    ValueError,
                ):
                    invalid += 1

            lines.extend(
                (
                    f"{pool.title()} total seeds: "
                    f"{len(seeds)}",
                    f"{pool.title()} valid seeds: "
                    f"{valid}",
                    f"{pool.title()} invalid seeds: "
                    f"{invalid}",
                    (
                        f"{pool.title()} duplicates: "
                        f"{len(seeds) - len(set(seeds))}"
                    ),
                )
            )

        report_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

        self.status.set(
            f"Validation report written to "
            f"{report_path.name}."
        )

    def _run(self) -> None:
        threads = [
            threading.Thread(
                target=controller.run,
                daemon=True,
            )
            for controller in self.controllers
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        errors = [
            controller.progress.error
            for controller in self.controllers
            if controller.progress.error
        ]

        self.root.after(
            0,
            lambda: self.status.set(
                errors[0]
                if errors
                else "Finished."
            ),
        )

    def pause(self) -> None:
        for controller in getattr(
            self,
            "controllers",
            [],
        ):
            controller.pause()

        if self.controller:
            self.status.set(
                "Paused; in-flight checks may finish safely."
            )

    def resume(self) -> None:
        for controller in getattr(
            self,
            "controllers",
            [],
        ):
            controller.resume()

        if self.controller:
            self.status.set(
                "Resumed."
            )

    def stop(self) -> None:
        for controller in getattr(
            self,
            "controllers",
            [],
        ):
            controller.stop()

        if self.controller:
            self.status.set(
                "Stopping safely."
            )

    def export(self) -> None:
        self.overworld_cache.export()
        self.nether_cache.export()

        self.status.set(
            "Exported overworld_seeds.txt and "
            "nether_seeds.txt."
        )

    def _on_progress(
        self,
        progress: Progress,
        pool: str,
    ) -> None:
        elapsed = max(
            0.001,
            time.monotonic()
            - progress.started_at,
        )

        self.root.after(
            0,
            lambda: self._update(
                progress,
                elapsed,
            ),
        )

    def _update(
        self,
        progress: Progress,
        elapsed: float,
    ) -> None:
        self.labels["cached"].set(
            f"{self.overworld_cache.count()} / {self.nether_cache.count()}"
        )

        self.labels["found"].set(
            (
                f"{self.controllers[0].progress.found} / "
                f"{self.controllers[0].progress.found}"
            )
            if hasattr(self, "controllers")
            else str(progress.found)
        )

        self.labels["tested"].set(
            str(
                sum(
                    controller.progress.candidates
                    for controller in getattr(
                        self,
                        "controllers",
                        [],
                    )
                )
                or progress.candidates
            )
        )

        self.labels["speed"].set(
            f"{progress.candidates / elapsed:.1f} seeds/sec"
        )

    def _refresh(self) -> None:
        self.labels["cached"].set(
            f"{self.overworld_cache.count()} / {self.nether_cache.count()}"
        )

        self.root.after(
            1000,
            self._refresh,
        )


def run_app(workdir: Path) -> None:
    root = tk.Tk()

    app = App(
        root,
        workdir,
    )

    root.protocol(
        "WM_DELETE_WINDOW",
        lambda: (
            app.stop(),
            root.destroy(),
        ),
    )

    root.mainloop()








if __name__ == "__main__":
    run_app(Path(os.environ["LOCALAPPDATA"]) / "MCSR26SeedFilter")




