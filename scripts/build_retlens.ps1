<#
.SYNOPSIS
  Build RetLens as a windowed one-folder program: dist\RetLens\RetLens.exe.

.DESCRIPTION
  1. tools\stage_resources.py lays out the read-only resources (G1 assets, configs, labels,
     docs, Isaac sources, licences) in build\resources.
  2. PyInstaller (packaging\retlens.spec) bundles Python, Qt / WebEngine, the retlens code
     and those resources into dist\RetLens.
  Needs pyinstaller in the conda env (conda-forge). Isaac Sim, Blender and the SMPL-X models
  are not bundled: each user installs them and picks them in RetLens's environment settings.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build_retlens.ps1
  powershell -ExecutionPolicy Bypass -File scripts\build_retlens.ps1 -Samples
  powershell -ExecutionPolicy Bypass -File scripts\build_retlens.ps1 -Samples -DistDir build\release
    (another output folder: dist\RetLens cannot be replaced while a RetLens runs from it; then
     package_release.ps1 -Dist build\release\RetLens)
#>
param(
    [string]$EnvName = "retlens",
    [switch]$Samples,  # also ship the CMU sample motions (redistributable)
    [string]$DistDir = "dist"  # the output folder (RetLens\ goes inside it)
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
$distRoot = if ([IO.Path]::IsPathRooted($DistDir)) { $DistDir } else { Join-Path $root $DistDir }
& $conda run --no-capture-output -n $EnvName pyinstaller packaging\retlens.spec --noconfirm --clean `
    --distpath $distRoot --workpath (Join-Path $root "build\pyinstaller")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (a RetLens running from $distRoot\RetLens keeps it from being replaced: close it, or use -DistDir)" }

# the update helper (one file) goes into the program folder; then the manifest of every file (retlens/install.py)
$app = Join-Path $distRoot "RetLens"
$helper = Join-Path $distRoot "retlens-update.exe"
if (-not (Test-Path $helper)) { throw "$helper was not built" }
Move-Item $helper (Join-Path $app "retlens-update.exe") -Force
& $conda run --no-capture-output -n $EnvName python tools\write_build_manifest.py $app
if ($LASTEXITCODE -ne 0) { throw "writing the build manifest failed" }

$exe = Join-Path $app "RetLens.exe"
$size = (Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("built {0} ({1:N0} MB in {2})" -f $exe, $size, $app)
