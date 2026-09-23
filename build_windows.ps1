$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
Set-Location $RepoRoot

$Repo = "https://github.com/69gg/MCSeedFinder.git"
$Commit = "9087c5dc64f2bc12d55609f44ff85fb5b14fc802"
$TrustedBackendSha256 = "79EE7CCB48F3F7ADEBEF06DF79FD314700A80B3FC74112819C1F6F9FDD328142"
$BackendSource = Join-Path $env:TEMP "mcseedfinder-26.2-$Commit"

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
    if (Test-Path (Join-Path $cargoBin "cargo.exe")) {
        $env:Path = "$cargoBin;$env:Path"
    }
}

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust Cargo is required. Install the official stable toolchain with https://win.rustup.rs/x86_64, restart PowerShell, and rerun this script."
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to obtain the pinned MCSeedFinder source."
}

$vswhereCandidates = @(
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\Installer\vswhere.exe"
)

$vswhere = $vswhereCandidates |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1

$devCmd = $null

if ($vswhere) {
    $installationPath = (
        & $vswhere -latest -products * -property installationPath 2>$null |
        Select-Object -First 1
    )

    if ($installationPath) {
        $devCmd = Join-Path $installationPath "Common7\Tools\VsDevCmd.bat"
    }
}

if (-not $devCmd) {
    $devCmd = @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat",
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"
    ) |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1
}

if (-not $devCmd) {
    throw "Visual Studio Build Tools 2022 was not found. Install the official Desktop development with C++ workload, including MSVC v143 and a Windows SDK."
}

$envLines = cmd.exe /c "`"$devCmd`" -arch=x64 -host_arch=x64 >nul && set"

foreach ($line in $envLines) {
    if ($line -match "^([^=]+)=(.*)$") {
        [Environment]::SetEnvironmentVariable(
            $Matches[1],
            $Matches[2],
            "Process"
        )
    }
}

# Restore the clang-cl toolchain used successfully for the pinned backend.
$llvmBin = "C:\Program Files\LLVM\bin"

if (Test-Path (Join-Path $llvmBin "clang-cl.exe")) {
    $env:Path = "$llvmBin;$env:Path"
    $env:CC_x86_64_pc_windows_msvc = "clang-cl.exe"
    $env:AR_x86_64_pc_windows_msvc = "llvm-lib.exe"
}

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    throw "Visual Studio was found at '$devCmd', but cl.exe is unavailable after x64 environment initialization."
}

if (-not (Get-Command link.exe -ErrorAction SilentlyContinue)) {
    throw "Visual Studio was found at '$devCmd', but link.exe is unavailable after x64 environment initialization."
}

if (-not (Get-Command clang-cl.exe -ErrorAction SilentlyContinue)) {
    throw "clang-cl.exe was not found. LLVM is required for the pinned MCSeedFinder native C sources."
}

if (-not (Get-Command llvm-lib.exe -ErrorAction SilentlyContinue)) {
    throw "llvm-lib.exe was not found. LLVM is required for the pinned MCSeedFinder native C sources."
}

Write-Host "Using clang-cl: $((Get-Command clang-cl.exe).Source)"
Write-Host "Using llvm-lib: $((Get-Command llvm-lib.exe).Source)"

if (Test-Path $BackendSource) {
    git -C $BackendSource fetch --all --tags
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to update the pinned MCSeedFinder source repository."
    }
}
else {
    git clone $Repo $BackendSource
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to clone the pinned MCSeedFinder source repository."
    }
}

git -C $BackendSource checkout --detach $Commit
if ($LASTEXITCODE -ne 0) {
    throw "Failed to check out pinned commit $Commit."
}

$actualCommit = (git -C $BackendSource rev-parse HEAD).Trim()

if ($actualCommit -ne $Commit) {
    throw "Pinned source checkout mismatch: expected $Commit, got $actualCommit."
}

$manifest = Join-Path $BackendSource "Cargo.toml"

Write-Host ""
Write-Host "Building pinned MCSeedFinder commit $Commit ..."
Write-Host ""

cargo build --manifest-path $manifest --release --locked

if ($LASTEXITCODE -ne 0) {
    throw "Cargo build FAILED with exit code $LASTEXITCODE. Package creation has been stopped."
}

$releaseDir = Join-Path $BackendSource "target\release"

$targets = cargo metadata --manifest-path $manifest --no-deps --format-version 1 | ConvertFrom-Json

if ($LASTEXITCODE -ne 0) {
    throw "Cargo metadata failed with exit code $LASTEXIT."
}

$binaryNames = @(
    $targets.packages |
    ForEach-Object {
        $_.targets |
        Where-Object { $_.kind -contains "bin" } |
        ForEach-Object { $_.name }
    }
)

$BackendBinary = $null

foreach ($binaryName in $binaryNames) {
    $candidate = Join-Path $releaseDir ($binaryName + ".exe")

    if (Test-Path $candidate) {
        $BackendBinary = $candidate
        break
    }
}

if (-not $BackendBinary) {
    throw "Pinned backend build completed without producing a Cargo binary. Expected one of: $($binaryNames -join ', ')."
}

$builtHash = (
    Get-FileHash $BackendBinary -Algorithm SHA256
).Hash.ToUpperInvariant()

Write-Host ""
Write-Host "Freshly compiled backend SHA-256:"
Write-Host $builtHash
Write-Host ""

if ($builtHash -ne $TrustedBackendSha256) {
    Write-Warning "Fresh Cargo build does not match the already verified provider binary."
    Write-Warning "The verified local provider will be used instead of silently trusting a new binary."

    $verifiedLocalBackend = Join-Path `
        $env:LOCALAPPDATA `
        "MCSR26SeedFilter\backend\mcseed-finder.exe"

    if (-not (Test-Path $verifiedLocalBackend)) {
        throw "Fresh backend hash differs from trusted hash and no verified local backend exists."
    }

    $verifiedLocalHash = (
        Get-FileHash $verifiedLocalBackend -Algorithm SHA256
    ).Hash.ToUpperInvariant()

    if ($verifiedLocalHash -ne $TrustedBackendSha256) {
        throw "Existing local backend does not match the trusted SHA-256 either."
    }

    $BackendBinary = $verifiedLocalBackend

    Write-Host "Using already verified local backend:"
    Write-Host $BackendBinary
}
else {
    Write-Host "Fresh backend matches the trusted SHA-256."
}

if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}

New-Item -ItemType Directory -Force "dist\backend" | Out-Null

Copy-Item $BackendBinary "dist\backend\mcseed-finder.exe"

$packagedHash = (
    Get-FileHash "dist\backend\mcseed-finder.exe" -Algorithm SHA256
).Hash.ToUpperInvariant()

if ($packagedHash -ne $TrustedBackendSha256) {
    throw "Packaged backend SHA-256 mismatch. Expected $TrustedBackendSha256 but got $packagedHash."
}

Get-ChildItem $releaseDir -Filter "*.dll" -File |
    Copy-Item -Destination "dist\backend" -Force

Copy-Item "config.json","README.md","THIRD_PARTY_NOTICES.md" "dist"

Write-Host ""
Write-Host "Building Windows application..."
Write-Host ""

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name MCSR26SeedFilter `
    --paths . `
    launcher.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path "dist\MCSR26SeedFilter.exe")) {
    throw "Application packaging did not produce dist\MCSR26SeedFilter.exe."
}

$env:MCSEED_FINDER_EXE = (
    Resolve-Path "dist\backend\mcseed-finder.exe"
).Path

Write-Host ""
Write-Host "Verifying packaged backend..."
Write-Host ""

& $env:MCSEED_FINDER_EXE --version

if ($LASTEXITCODE -ne 0) {
    throw "Bundled MCSeedFinder backend failed its version command."
}

$finalHash = (
    Get-FileHash $env:MCSEED_FINDER_EXE -Algorithm SHA256
).Hash.ToUpperInvariant()

if ($finalHash -ne $TrustedBackendSha256) {
    throw "Final packaged backend hash mismatch."
}

python -c "from pathlib import Path; from mcsr_filter.engine import create_provider; p=create_provider(Path.cwd()); r=p.self_test(); print(r); raise SystemExit(0 if r.verified else 1)"

if ($LASTEXITCODE -ne 0) {
    throw "Bundled backend failed the application provider self-test."
}

Write-Host ""
Write-Host "Running application test suite..."
Write-Host ""

python -m unittest discover -s tests -v

if ($LASTEXITCODE -ne 0) {
    throw "Application test suite FAILED with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "=============================================="
Write-Host "BUILD SUCCESSFUL"
Write-Host "=============================================="
Write-Host "Package: dist\MCSR26SeedFilter.exe"
Write-Host "Backend SHA-256: $finalHash"
Write-Host "=============================================="