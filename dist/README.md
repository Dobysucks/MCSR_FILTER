# MCSR 26.2 Seed Filter :D

This repository contains a Windows-friendly Tkinter application and command-line
runtime for cumulative, independent Overworld and Nether seed filtering. It
persists accepted seeds in SQLite, keeps `overworld_seeds.txt` and
`nether_seeds.txt` synchronized, supports pause/resume/stop, and exposes a
version-specific Minecraft world-generation provider interface.

## Important Minecraft 26.2 limitation

The application integrates the MIT-licensed `69gg/MCSeedFinder` backend
(commit `9087c5dc64f2bc12d55609f44ff85fb5b14fc802`) when its executable is
present. The backend's checked-in native profile selects Minecraft 26.2.
Set `MCSEED_FINDER_EXE` or place `mcseed-finder.exe` beside the app, then use
**VERIFY PROVIDER**. The provider self-test checks the reported version, the
26.2 structure registry, and a known-seed JSON report.

The checked-in executable is built without a backend when Cargo is unavailable,
but `build_windows.ps1` produces the self-contained package by building the
real backend into `dist\backend\mcseed-finder.exe`. Without that artifact, or
if the first-run self-test fails, generation remains disabled. v2 does not
require loot, lava pools, Magma Ravines, or open terrain; only real 26.2
structure queries are required.
It never uses 1.16.1/1.21.x constants or approximations.

## Requirements

- Windows 10/11 (Python 3.11+ for source execution)
- Tkinter (included with the standard Windows Python installer)
- No third-party runtime dependency is required
- Optional: PyInstaller for building the Windows executable

## Run from source

```powershell
py -m mcsr_filter
```

The application creates `mcsr_26_2_seed_cache.db`, two pool TXT files,
`config.json`, and
`logs/generation.log` in the selected working directory. The CLI is also
available:

```powershell
py -m mcsr_filter.cli --help
```

## Configuration

`config.json` is created automatically. `minecraft_version` must remain exactly
`26.2`. The filter version is `MCSR-26.2-ADAPTED-v2`. `target_overworld` and
`target_nether` are the numbers of **new** seeds
requested for the next run. Workers may be `0` for automatic CPU selection.
Filters can be toggled
individually, but they are only evaluated after a real 26.2 provider is
installed.

## Cache, import, recovery, and export

On startup the cache opens SQLite, imports valid one-seed-per-line values from
each pool TXT file, removes duplicate lines, and rewrites the pool files from the
database when necessary. Seeds are stored as `TEXT` so the complete signed
64-bit range is preserved. The database has a unique seed constraint and stores
Minecraft and filter versions with every row. Export is atomic and never
overwrites the cumulative history with a partial result.

Deleting either TXT file is recoverable from SQLite. Deleting the database is
recoverable from the matching TXT files. To intentionally clear all history,
stop the app and remove `mcsr_26_2_seed_cache.db`, `overworld_seeds.txt`, and
`nether_seeds.txt`.

## Pause/resume and multithreading

Workers draw random signed 64-bit candidates from the complete Java seed range.
The controller uses a stop event, a pause event, bounded worker threads, and a
single SQLite writer path. Pause stops new work after in-flight checks finish;
resume continues with the same target. Progress is periodically checkpointed
in `generation_state.json`. A restart safely recovers all committed seeds.

## Windows executable

Install PyInstaller and build a single-file executable:

```powershell
py -m pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name MCSR26SeedFilter --paths . mcsr_filter\__main__.py
```

The output is `dist\MCSR26SeedFilter.exe`. Run it from a writable directory so
the database, configuration, log, and pool TXT files can be created beside the
executable. The executable is usable without Python installed, but it still
requires a real 26.2 provider to perform generation.

For a self-contained package, install Git, Python, and the official Rust
toolchain. On Windows, install Rustup from
`https://win.rustup.rs/x86_64` (or `winget install Rustlang.Rustup`), then
install Visual Studio Build Tools 2022 with the **Desktop development with
C++** workload so that the MSVC `link.exe` is available. Open a Developer
PowerShell after installation and run:

```powershell
.\build_windows.ps1
```

This checks out MCSeedFinder commit
`9087c5dc64f2bc12d55609f44ff85fb5b14fc802`, builds its real Rust/native
backend with Cargo, locates the actual Cargo binary target, copies the
resulting executable and any release DLLs to `dist\backend\`, packages the GUI,
invokes the bundled backend, and runs the tests. Runtime discovery order is
bundled `dist\backend`, application-local, `MCSEED_FINDER_EXE`, then `PATH`. If
Cargo or the MSVC linker is unavailable, the script stops with the exact
missing-tool error and no fake backend is produced.

### End-user backend installation

The GUI also checks `%LOCALAPPDATA%\MCSR26SeedFilter\backend\` and can reuse a
previously verified backend while offline. It will never download an arbitrary
executable. At the pinned MCSeedFinder commit
`9087c5dc64f2bc12d55609f44ff85fb5b14fc802`, upstream publishes source only:
there is no official Windows x64 release asset, CI artifact, or published
SHA-256 manifest that can be trusted for an automatic download. Consequently
the **INSTALL 26.2 SEED ENGINE** action reports this exact blocker and leaves
the provider disabled; source builds must use `build_windows.ps1`. The runtime
installer framework accepts a future pinned artifact only when its URL,
SHA-256, version, commit, startup, and provider health checks all pass, and it
installs atomically without replacing a verified backend.

## Tests

```powershell
py -m unittest discover -s tests -v
```

The tests cover signed seed handling, import/export and recovery, SQLite
uniqueness and concurrent insertion, configuration/version validation,
pause/resume, deterministic candidate generation, and repeated-run duplicate
prevention using an explicit test provider. The test provider is not shipped or
used by the production application as a Minecraft implementation.
