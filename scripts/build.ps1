[CmdletBinding()]
param(
    [ValidateSet('release', 'dev-small')][string]$Profile = 'release',
    [switch]$Doctor,
    [switch]$FetchOnly,
    [switch]$UiPreview
)

$ErrorActionPreference = 'Stop'
if ($UiPreview -and ($Doctor -or $FetchOnly)) { throw '-UiPreview cannot be combined with -Doctor or -FetchOnly.' }
$mycodxRoot = Split-Path -Parent $PSScriptRoot
$mycodxBuild = Join-Path $mycodxRoot '.build'
$env:CARGO_HOME = Join-Path $mycodxBuild 'cargo'
$mycodxLocalRustup = Join-Path $mycodxBuild 'rustup'
if (Test-Path -LiteralPath $mycodxLocalRustup) { $env:RUSTUP_HOME = $mycodxLocalRustup }
$env:PATH = (Join-Path $env:CARGO_HOME 'bin') + ';' + (Join-Path $env:USERPROFILE '.cargo\bin') + ';' + $env:PATH
$env:CARGO_TARGET_DIR = Join-Path $mycodxBuild 'target'
$env:PYTHONUTF8 = '1'

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue) -or -not (Get-Command cmake.exe -ErrorAction SilentlyContinue)) {
    $mycodxVswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $mycodxVswhere) {
        $mycodxVisualStudio = & $mycodxVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($mycodxVisualStudio) {
            if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
                $mycodxDevShell = Join-Path $mycodxVisualStudio 'Common7\Tools\Launch-VsDevShell.ps1'
                & $mycodxDevShell -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
            }
            $env:PATH = (Join-Path $mycodxVisualStudio 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin') + ';' + $env:PATH
        }
    }
}

$mycodxAction = if ($UiPreview) { 'ui-build' } elseif ($Doctor) { 'doctor' } elseif ($FetchOnly) { 'fetch' } else { 'build' }
$mycodxLogDir = Join-Path $mycodxBuild 'logs'
New-Item -ItemType Directory -Path $mycodxLogDir -Force | Out-Null
$mycodxLog = Join-Path $mycodxLogDir ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + $mycodxAction + '.log')
$mycodxExitCode = 1
$env:MYCODX_BUILD_LOG = $mycodxLog
try {
    if ($UiPreview) {
        & python (Join-Path $PSScriptRoot 'ui.py') build
    } else {
        & python (Join-Path $PSScriptRoot 'manage.py') $mycodxAction --profile $Profile
    }
    $mycodxExitCode = $LASTEXITCODE
} finally {
    Write-Host "Build log: $mycodxLog"
}
exit $mycodxExitCode
