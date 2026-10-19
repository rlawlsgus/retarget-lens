<#
.SYNOPSIS
  Create/update the k-humanoid conda env and link it to the global Isaac Sim.

.DESCRIPTION
  1. conda env create/update from environment.yml (conda-forge only).
  2. Installs activate.d / deactivate.d hooks (cmd + PowerShell) that set the
     same variables C:\isaacsim\python.bat sets (CARB_APP_PATH, ISAAC_PATH,
     EXP_PATH, PYTHONPATH -> <isaacsim>\site). Isaac Sim's sitecustomize.py then
     adds its packages to sys.path, so plain `python` in the env can
     `from isaacsim import SimulationApp`. Nothing is copied into the env.
  3. Runs scripts\install_gmr.ps1 (GMR retargeter, pinned commit, ~53 MB,
     next to the project folder). Skip with -SkipGmr.

  -HooksOnly skips step 1, for an env created from environment.lock.txt
  (see docs/setup.md): the env update would re-resolve the locked builds.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1
  conda activate k-humanoid
  python -c "from isaacsim import SimulationApp; print('ok')"
#>
param(
    [string]$EnvName = "k-humanoid",
    [string]$IsaacSimPath = "C:\isaacsim",
    [switch]$SkipGmr,
    [switch]$HooksOnly
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# --- locate conda
$conda = $env:CONDA_EXE
if (-not $conda) {
    foreach ($base in @("$env:LOCALAPPDATA\miniconda3", "$env:USERPROFILE\miniconda3", "$env:USERPROFILE\anaconda3",
                        "$env:LOCALAPPDATA\anaconda3", "C:\ProgramData\miniconda3", "C:\ProgramData\anaconda3",
                        "$env:USERPROFILE\miniforge3")) {
        if (Test-Path "$base\Scripts\conda.exe") { $conda = "$base\Scripts\conda.exe"; break }
    }
}
if (-not $conda) { throw "conda not found. Install Miniconda/Miniforge first." }
Write-Host "conda: $conda"

# --- create or update env. This network gets HTTP 429 "registration required"
# from repo.anaconda.com, so restrict this process to conda-forge.
$env:CONDA_CHANNELS = "conda-forge"
$exists = (& $conda env list) -match "^\s*$([regex]::Escape($EnvName))\s"
if ($HooksOnly) {
    if (-not $exists) { throw "env $EnvName not found; create it first (docs/setup.md)" }
} else {
    Push-Location $ProjectRoot
    try {
        if ($exists) { & $conda env update -n $EnvName -f environment.yml --prune }
        else { & $conda env create -n $EnvName -f environment.yml --yes }
        if ($LASTEXITCODE -ne 0) { throw "conda env create/update failed" }
    } finally { Pop-Location }
}

$prefix = (& $conda run -n $EnvName python -c "import sys; print(sys.prefix)").Trim()
Write-Host "env prefix: $prefix"

# --- activation hooks
if (-not (Test-Path "$IsaacSimPath\site\sitecustomize.py")) {
    Write-Warning "Isaac Sim not found at $IsaacSimPath (run scripts\install_isaacsim.ps1). Hooks are installed anyway."
}
$act = Join-Path $prefix "etc\conda\activate.d"
$deact = Join-Path $prefix "etc\conda\deactivate.d"
New-Item -ItemType Directory -Force -Path $act, $deact | Out-Null

@"
@REM k-humanoid: link global Isaac Sim (mirrors $IsaacSimPath\python.bat)
@set "KH_OLD_PYTHONPATH=%PYTHONPATH%"
@set "ISAACSIM_PATH=$IsaacSimPath"
@set "CARB_APP_PATH=$IsaacSimPath\kit"
@set "ISAAC_PATH=$IsaacSimPath\"
@set "EXP_PATH=$IsaacSimPath\apps"
@set "PYTHONPATH=$IsaacSimPath\site;%PYTHONPATH%"
"@ | Set-Content -Encoding ascii (Join-Path $act "isaacsim_link.bat")

@"
@set "PYTHONPATH=%KH_OLD_PYTHONPATH%"
@set "KH_OLD_PYTHONPATH="
@set "ISAACSIM_PATH="
@set "CARB_APP_PATH="
@set "ISAAC_PATH="
@set "EXP_PATH="
"@ | Set-Content -Encoding ascii (Join-Path $deact "isaacsim_link.bat")

@"
# k-humanoid: link global Isaac Sim (mirrors $IsaacSimPath\python.bat)
`$env:KH_OLD_PYTHONPATH = `$env:PYTHONPATH
`$env:ISAACSIM_PATH = "$IsaacSimPath"
`$env:CARB_APP_PATH = "$IsaacSimPath\kit"
`$env:ISAAC_PATH = "$IsaacSimPath\"
`$env:EXP_PATH = "$IsaacSimPath\apps"
`$env:PYTHONPATH = (@("$IsaacSimPath\site", `$env:PYTHONPATH) | Where-Object { `$_ }) -join ";"
"@ | Set-Content -Encoding ascii (Join-Path $act "isaacsim_link.ps1")

@"
`$env:PYTHONPATH = `$env:KH_OLD_PYTHONPATH
foreach (`$v in "KH_OLD_PYTHONPATH", "ISAACSIM_PATH", "CARB_APP_PATH", "ISAAC_PATH", "EXP_PATH") {
    Remove-Item "Env:`$v" -ErrorAction SilentlyContinue
}
"@ | Set-Content -Encoding ascii (Join-Path $deact "isaacsim_link.ps1")

if (-not $SkipGmr) {
    & (Join-Path $PSScriptRoot "install_gmr.ps1") -EnvName $EnvName
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  conda activate $EnvName"
Write-Host "  python tools\make_samples.py"
Write-Host "  python tools\isaac_replay.py --human data\samples\synthetic_walk_glitch.bvh"
Write-Host "  python tools\fetch_samples.py; python tools\retarget.py data\raw\cmu_bvh"
