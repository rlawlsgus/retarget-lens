<#
.SYNOPSIS
  Build RetLens as a windowed one-folder program: dist\RetLens\RetLens.exe.

.DESCRIPTION
  1. tools\stage_resources.py lays out the read-only resources (G1 assets, configs, labels,
     docs, Isaac sources, licences) in build\resources.
  2. PyInstaller (packaging\retlens.spec) bundles Python, Qt / WebEngine, the khumanoid code
     and those resources into dist\RetLens.
  Needs pyinstaller in the conda env (conda-forge). Isaac Sim, Blender and the SMPL-X models
  are not bundled: each user installs them and picks them in RetLens's environment settings.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build_retlens.ps1
  powershell -ExecutionPolicy Bypass -File scripts\build_retlens.ps1 -Samples
#>
param(
    [string]$EnvName = "k-humanoid",
    [switch]$Samples  # also ship the CMU sample motions (redistributable)
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$conda = (Get-Command conda.exe -ErrorAction SilentlyContinue).Source
foreach ($c in @("$env:LOCALAPPDATA\miniconda3\Scripts\conda.exe", "$env:USERPROFILE\miniconda3\Scripts\conda.exe")) {
    if (-not $conda -and (Test-Path $c)) { $conda = $c }
}
if (-not $conda) { throw "conda was not found" }

$res = Join-Path $root "build\resources"
$stageArgs = @("tools\stage_resources.py", $res)
if ($Samples) { $stageArgs += "--samples" }
& $conda run --no-capture-output -n $EnvName python @stageArgs
if ($LASTEXITCODE -ne 0) { throw "staging the resources failed" }

$env:RETLENS_RESOURCES = $res
& $conda run --no-capture-output -n $EnvName pyinstaller packaging\retlens.spec --noconfirm --clean `
    --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build\pyinstaller")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $root "dist\RetLens\RetLens.exe"
$size = (Get-ChildItem (Join-Path $root "dist\RetLens") -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("built {0} ({1:N0} MB in dist\RetLens)" -f $exe, $size)
