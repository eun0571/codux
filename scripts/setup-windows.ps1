# Run in a normal Windows PowerShell terminal. Downloads require internet access.
# Rust stays under this workspace; the optional C++ tools use Microsoft's system installer.
[CmdletBinding()]
param([switch]$InstallCppBuildTools)

$ErrorActionPreference = 'Stop'
$mycodxRoot = Split-Path -Parent $PSScriptRoot
$mycodxLock = Get-Content -LiteralPath (Join-Path $mycodxRoot 'upstream.lock.json') -Raw | ConvertFrom-Json
$mycodxBuild = Join-Path $mycodxRoot '.build'
$mycodxVswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'

function Find-MycodxCppTools {
    if (Test-Path -LiteralPath $mycodxVswhere) {
        & $mycodxVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    }
}

if (-not (Find-MycodxCppTools)) {
    if (-not $InstallCppBuildTools) {
        throw 'MSVC C++ tools are missing. To install them, rerun this script with -InstallCppBuildTools.'
    }
    Write-Host 'Installing Microsoft C++ Build Tools and Windows SDK.'
    & winget install --exact --id Microsoft.VisualStudio.2022.BuildTools --accept-source-agreements --accept-package-agreements --override '--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.CMake.Project --includeRecommended'
    if ($LASTEXITCODE -notin @(0, 3010)) { throw "C++ installer failed: $LASTEXITCODE" }
    if (-not (Find-MycodxCppTools)) { throw 'C++ tools were not found after installation. Finish the installer or reboot, then rerun.' }
}

$mycodxOldCargo = $env:CARGO_HOME
$mycodxOldRustup = $env:RUSTUP_HOME
try {
    $env:CARGO_HOME = Join-Path $mycodxBuild 'cargo'
    $env:RUSTUP_HOME = Join-Path $mycodxBuild 'rustup'
    $mycodxRustup = Join-Path $env:CARGO_HOME 'bin\rustup.exe'
    if (-not (Test-Path -LiteralPath $mycodxRustup)) {
        $mycodxDownloads = Join-Path $mycodxBuild 'downloads'
        New-Item -ItemType Directory -Path $mycodxDownloads -Force | Out-Null
        $mycodxUrl = 'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe'
        $mycodxInstaller = Join-Path $mycodxDownloads 'rustup-init.exe'
        Invoke-WebRequest -UseBasicParsing -Uri $mycodxUrl -OutFile $mycodxInstaller
        $mycodxChecksum = Join-Path $mycodxDownloads 'rustup-init.exe.sha256'
        Invoke-WebRequest -UseBasicParsing -Uri "$mycodxUrl.sha256" -OutFile $mycodxChecksum
        $mycodxDigest = (Get-Content -LiteralPath $mycodxChecksum -Raw).Trim().Split(' ')[0]
        if ($mycodxDigest -notmatch '^[0-9a-fA-F]{64}$' -or (Get-FileHash -LiteralPath $mycodxInstaller -Algorithm SHA256).Hash -ne $mycodxDigest) {
            throw 'Rustup installer checksum mismatch.'
        }
        & $mycodxInstaller -y --no-modify-path --profile minimal --default-host x86_64-pc-windows-msvc --default-toolchain $mycodxLock.rust_toolchain
        if ($LASTEXITCODE -ne 0) { throw "Rustup installation failed: $LASTEXITCODE" }
    }
    & $mycodxRustup toolchain install $mycodxLock.rust_toolchain --profile minimal --component rustfmt --component clippy --no-self-update
    if ($LASTEXITCODE -ne 0) { throw "Rust toolchain installation failed: $LASTEXITCODE" }
    Write-Host 'Toolchain ready. Build: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1'
} finally {
    $env:CARGO_HOME = $mycodxOldCargo
    $env:RUSTUP_HOME = $mycodxOldRustup
}
