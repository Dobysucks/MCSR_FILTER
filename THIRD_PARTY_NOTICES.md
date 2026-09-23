# Third-party backend investigation

The verified backend candidate is [69gg/MCSeedFinder](https://github.com/69gg/MCSeedFinder),
commit `9087c5dc64f2bc12d55609f44ff85fb5b14fc802` (MIT). Its checked-in
`native/version.h` selects `MC_26_2`, its vendored Cubiomes snapshot includes
the 26.2 biome/structure profile, and its README documents 26.2-specific
generation and tests. The Python application integrates it through
`MCSEED_FINDER_EXE` or `mcseed-finder.exe` in the application directory.

The repository also reviewed:

- `CJH3139/SeedScout` (Apache-2.0): a Fabric client-side map mod, not a
  standalone seed-search provider.
- `watchingdogs/cubiomes-viewer-26-2` (GPL-3.0): a GUI fork; it was not
  selected because its README documents approximate terrain behavior and it
  does not expose the required application provider contract.

The checked-in source does not include a prebuilt backend binary. The
`build_windows.ps1` pipeline obtains the pinned source and builds the real
Rust/native executable into `dist\backend\mcseed-finder.exe`; it then runs the
application provider self-test against that exact artifact. The Windows MSVC
Rust target also requires Visual Studio Build Tools with the Desktop
development with C++ workload (`link.exe`). If Rust/Cargo, the linker, or
compilation is unavailable, no backend is produced and generation remains
disabled. v2 does not require loot, lava pools, Magma Ravines, or open terrain.
The application never substitutes an older Minecraft version or an
approximation.

No official precompiled Windows x64 artifact or trusted checksum was found
for the pinned commit. The application therefore does not auto-download or
execute a backend at first run. It may reuse a locally installed and verified
artifact under `%LOCALAPPDATA%\MCSR26SeedFilter\backend` when a future trusted
manifest is provided; otherwise the UI remains fail-closed and directs users
to the source-build path.
