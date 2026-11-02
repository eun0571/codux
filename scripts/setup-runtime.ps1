param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$npmCommand = Get-Command npm.cmd -ErrorAction Stop
$nodeCommand = Get-Command node.exe -ErrorAction Stop
foreach ($name in @('mermaid-product', 'mermaid-live', 'mermaid-text')) {
    $runtimeRoot = Join-Path $projectRoot ('.build\' + $name + '-runtime')
    $sourceRoot = Join-Path $projectRoot ('renderers\' + $name)
    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    foreach ($file in @('package.json', 'package-lock.json')) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot $file) -Destination $runtimeRoot
    }
    & $npmCommand.Source ci --prefix $runtimeRoot --ignore-scripts --no-audit --no-fund --cache (Join-Path $projectRoot '.build\npm-cache')
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed: $name" }
}
Write-Host 'Pinned runtime dependencies are ready. Node.js and installed Chrome/Edge are reused.'
