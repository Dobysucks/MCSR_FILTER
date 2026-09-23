# MCSR_FILTER

A Windows-friendly Minecraft Java 26.2 seed filtering tool for generating large, persistent pools of Overworld and Nether seeds using the native MCSeedFinder backend.

Built for MCSR-style seed filtering workflows, with separate Overworld and Nether generation, persistent SQLite history, TXT exports, pause/resume/stop controls, crash recovery, and a built-in provider verification test.

> **Important:** This is an independent/adapted seed filter. It is **not the official MCSR Ranked seed filter** and is not affiliated with MCSR Ranked.

---

## Features

- Minecraft Java 26.2
- Native MCSeedFinder backend
- Separate START OVERWORLD and START NETHER generation
- Up to 500,000 new seeds per dimension
- Persistent SQLite seed history
- Duplicate prevention
- Automatic TXT exports
- Pause / resume / stop
- Progress tracking
- Crash/restart recovery
- Built-in TEST 100 + 100
- Provider verification
- Windows Tkinter GUI
- No third-party Python runtime packages required

---

# Quick Start

## Windows

### 1. Download the application

Download the latest Windows release from the GitHub Releases page.

If you are running from source, see the Run From Source section below.

### 2. Start the application

Launch:

`MCSR26SeedFilter.exe`

Persistent application data is stored under:

`%LOCALAPPDATA%\MCSR26SeedFilter\`

### 3. Verify the seed engine

Click:

`VERIFY PROVIDER`

The application must report that the Minecraft 26.2 provider is verified before production generation is enabled.

The verified backend is the native MCSeedFinder implementation used by this project.

### 4. Run the built-in test

Click:

`TEST 100 + 100`

This runs a separate test for:

- 100 Overworld seeds
- 100 Nether seeds

The test uses temporary storage and does not add test seeds to your production database.

A successful test enables production generation.

### 5. Generate seeds

Choose the dimension you want:

`START OVERWORLD`

or:

`START NETHER`

The Overworld and Nether generators are independent.

Example:

`Overworld target: 500000`
`Nether target: 500000`

This requests up to 500,000 new accepted seeds for each pool.

---

# Filters

MCSR_FILTER provides structure-based filters for both dimensions.

## Overworld Filters

### Village

Searches for a Village near the Overworld spawn and applies the supported Village/blacksmith structure checks.

### Shipwreck

Searches for a Shipwreck near spawn using the supported Minecraft 26.2 structure-piece checks.

### Desert Temple

Searches for a Desert Pyramid near spawn together with the configured nearby biome requirement.

### Ruined Portal

Searches for a Ruined Portal near spawn using the native Minecraft 26.2 structure implementation.

### Buried Treasure

Searches for Buried Treasure near spawn.

---

# Nether Filters

Available Nether filters:

- Stables
- Treasure
- Bridge
- Housing
- Fortress

The Nether filter logic is:

`(Bastion subtype OR Housing) AND Fortress`

Therefore:

- Fortress alone is not enough.
- A Bastion subtype alone is not enough.
- A qualifying Bastion plus Fortress is required.

## Stables

Checks for the supported Stables Bastion structure piece.

## Treasure

Checks for the supported Treasure Bastion structure piece.

## Bridge

Checks for the supported Bridge Bastion structure piece.

## Housing

Represents a Bastion Remnant detected without one of the explicitly supported Stables, Treasure, or Bridge pieces.

## Fortress

Requires a Nether Fortress within the configured Nether search radius.

---

# MCSR Ranked Compatibility

MCSR_FILTER is designed around an MCSR-style structure filtering workflow.

It is **not the official MCSR Ranked seed filter**.

The official MCSR Ranked system includes additional requirements that are not all implemented here, including requirements related to:

- intended Bastion selection
- Bastion uniqueness and proximity
- terrain and open-path conditions
- loot requirements
- Fortress relationships
- other gameplay-specific seed criteria

This project focuses on structure and proximity filtering that its native Minecraft 26.2 backend can reliably evaluate.

A seed accepted by this application should therefore **not automatically be assumed to satisfy every official MCSR Ranked requirement**.

---

# Generation

## Targets

The GUI has independent targets for:

- Overworld
- Nether

A target represents the number of **new accepted seeds** requested for that pool.

Already accepted seeds remain in the persistent database and are not regenerated as duplicates.

Example:

`Overworld: 500000`
`Nether: 500000`
`Workers: 8`

---

# Workers

Workers control native backend CPU parallelism.

Eight workers is a reasonable starting point for many CPUs.

More workers are not automatically faster.

Performance depends on:

- CPU
- selected filters
- structure-check complexity
- database and disk performance
- native backend workload

Different filters can have dramatically different generation speeds.

---

# Pause / Resume / Stop

## PAUSE

Stops new generation work while allowing in-flight checks to finish safely.

## RESUME

Continues generation toward the current target.

## STOP

Safely stops generation while preserving committed results.

Previously accepted seeds remain in the database.

---

# Persistent Seed History

Accepted seeds are stored in SQLite.

The database prevents duplicate accepted seeds from being added again.

The application also maintains:

`overworld_seeds.txt`

and:

`nether_seeds.txt`

Each file contains one accepted seed per line.

The SQLite database is the persistent source of truth.

---

# Recovery

Generation progress is checkpointed.

If the application closes unexpectedly or Windows restarts, already committed seeds remain stored.

Restarting the application does not intentionally regenerate the existing accepted seed history.

---

# Data Location

Packaged Windows builds store persistent application data under:

`%LOCALAPPDATA%\MCSR26SeedFilter\`

Typical contents:

`MCSR26SeedFilter\`
`├── config.json`
`├── mcsr_26_2_seed_cache.db`
`├── overworld_seeds.txt`
`├── nether_seeds.txt`
`├── generation_state.json`
`├── logs\`
`└── backend\`
`    └── mcseed-finder.exe`

Do not delete the database if you want to preserve your accumulated seeds.

---

# Minecraft 26.2 Backend

The application uses the native MCSeedFinder backend for Minecraft Java 26.2.

Pinned upstream commit:

`9087c5dc64f2bc12d55609f44ff85fb5b14fc802`

Verified backend SHA-256:

`79EE7CCB48F3F7ADEBEF06DF79FD314700A80B3FC74112819C1F6F9FDD328142`

The application performs a provider self-test before enabling production generation.

This prevents an incompatible or unverified Minecraft seed-generation backend from silently being used.

---

# Running From Source

## Requirements

- Windows 10 or Windows 11
- Python 3.11+
- Tkinter
- Git
- Rust/Cargo if building the native backend yourself

Normal source execution does not require third-party Python runtime packages.

## Start the application

From the repository root:

`py -m mcsr_filter`

---

# Building Windows Releases

The repository includes:

- `build.ps1`
- `build_windows.ps1`
- `MCSR26SeedFilter.spec`

A complete native backend build requires the Rust toolchain and the required Windows C++ build tools.

Run:

`.\build_windows.ps1`

Build output is placed under:

`dist\`

---

# Running Automated Tests

Run the Python test suite:

`py -m unittest discover -s tests -v`

The GUI also contains:

`TEST 100 + 100`

This specifically tests both production dimensions using temporary test storage.

The test does not pollute the production seed database.

---

# Project Structure

`MCSR_FILTER/`
`├── mcsr_filter/`
`├── tests/`
`├── build.ps1`
`├── build_windows.ps1`
`├── pyproject.toml`
`├── README.md`
`├── THIRD_PARTY_NOTICES.md`
`└── .gitignore`

---

# Troubleshooting

## Provider not verified

Click:

`VERIFY PROVIDER`

Production generation requires a verified Minecraft 26.2 provider.

## Generation is slow

Try adjusting the worker count.

The native backend performs the expensive Minecraft structure checks, so performance depends heavily on the selected filters and CPU.

Complex Overworld filters can be substantially slower than simpler Nether structure filters.

## TEST 100 + 100 takes time

The test performs real native structure checks.

It is not an instant fake health check.

Depending on CPU and filter complexity, it may take some time.

The test uses temporary storage and does not add test seeds to your production database.

## Previous seeds are missing

Check:

`%LOCALAPPDATA%\MCSR26SeedFilter\`

Look for:

- `mcsr_26_2_seed_cache.db`
- `overworld_seeds.txt`
- `nether_seeds.txt`

Do not delete these files if you want to preserve your accumulated seed history.

## Generation is disabled

Run:

`VERIFY PROVIDER`

and make sure the provider self-test succeeds.

---

# Third-Party Notices

The project integrates the MIT-licensed MCSeedFinder backend.

See:

`THIRD_PARTY_NOTICES.md`

for licensing and attribution information.

---

# Disclaimer

MCSR_FILTER is an independent project.

It is not an official MCSR Ranked application and is not maintained by MCSR Ranked.

Minecraft is a trademark of Mojang Studios/Microsoft.

Use this project at your own discretion and verify generated seeds in your intended Minecraft/MCSR environment before relying on them for gameplay.

---

# Credits

- MCSeedFinder and its contributors
- Minecraft seed-generation research
- MCSR community research and publicly documented filtering concepts
