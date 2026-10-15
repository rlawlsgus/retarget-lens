<#
.SYNOPSIS
  Install GMR (General Motion Retargeting, MIT) into the k-humanoid env, without git.

.DESCRIPTION
  GMR's own dependencies come from environment.yml (conda-forge: mujoco-python,
  qpsolvers/daqp, pytorch CPU, ...; PyPI: mink, smplx). This script only adds
  GMR itself:

  1. Downloads a pinned GMR commit from GitHub, but only setup.py, LICENSE,
     README.md, general_motion_retargeting/ and assets/<robot>/ (about 53 MB for
     the G1, instead of the 1.2 GB full tree with every robot's meshes).
     Every file is checked against its git blob SHA-1 from the commit's tree.
  2. Links the checkout into the env with a .pth file. That is what
     `pip install -e` does, minus the build backend (which would pull setuptools
     from PyPI into an isolated build env).

  The checkout lives outside the project folder (default: ..\GMR next to it),
  like Isaac Sim lives in C:\isaacsim.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_gmr.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install_gmr.ps1 -Robots unitree_g1,unitree_h1
#>
param(
    [string]$EnvName = "k-humanoid",
    [string]$Dest = "",
    [string]$Commit = "bb1bbe40774794fceb2a7c579a3464a28e68c844",
    [string[]]$Robots = @("unitree_g1")
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar on
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Dest) { $Dest = Join-Path (Split-Path -Parent $ProjectRoot) "GMR" }
$Repo = "YanjieZe/GMR"

function Get-GitBlobSha1([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $header = [System.Text.Encoding]::ASCII.GetBytes("blob $($bytes.Length)`0")
    $sha = [System.Security.Cryptography.SHA1]::Create()
    $sha.TransformBlock($header, 0, $header.Length, $null, 0) | Out-Null
    $sha.TransformFinalBlock($bytes, 0, $bytes.Length) | Out-Null
    return ([System.BitConverter]::ToString($sha.Hash) -replace "-", "").ToLower()
}

# --- 1. pinned file list
Write-Host "GMR $Repo@$($Commit.Substring(0, 7)) -> $Dest"
$tree = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/git/trees/$Commit`?recursive=1" -TimeoutSec 60
if ($tree.truncated) { throw "GitHub returned a truncated tree; cannot verify the file list" }
$prefixes = @("general_motion_retargeting/") + ($Robots | ForEach-Object { "assets/$_/" })
$wanted = foreach ($item in $tree.tree) {
    if ($item.type -ne "blob") { continue }
    if (@("setup.py", "LICENSE", "README.md") -contains $item.path) { $item; continue }
    foreach ($pre in $prefixes) { if ($item.path.StartsWith($pre)) { $item; break } }
}
foreach ($r in $Robots) {
    if (-not ($wanted | Where-Object { $_.path -like "assets/$r/*" })) { throw "no assets/$r in GMR@$Commit" }
}
$totalMB = ($wanted | Measure-Object size -Sum).Sum / 1MB
Write-Host ("{0} files, {1:N1} MB" -f $wanted.Count, $totalMB)

# --- 2. download + verify (files already present with the right hash are kept)
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$destFull = (Resolve-Path $Dest).Path
$n = 0
foreach ($f in $wanted) {
    if ($f.path -match '(^|/)\.\.(/|$)' -or $f.path -match '^[/\\]' -or $f.path -match ':') { throw "unsafe path in tree: $($f.path)" }
    $out = Join-Path $destFull ($f.path -replace "/", "\")
    if ((Test-Path $out) -and (Get-GitBlobSha1 $out) -eq $f.sha) { continue }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/$Repo/$Commit/$($f.path)" -OutFile $out -UseBasicParsing -TimeoutSec 120
    if ((Get-GitBlobSha1 $out) -ne $f.sha) { Remove-Item $out; throw "SHA-1 mismatch: $($f.path)" }
    $n++
}
Write-Host "downloaded $n file(s), all $($wanted.Count) verified"
@"
repo: https://github.com/$Repo
commit: $Commit
robots: $($Robots -join ", ")
installed_by: K-Humanoid scripts\install_gmr.ps1 (partial checkout, not a git clone)
"@ | Set-Content -Encoding ascii (Join-Path $destFull "GMR_COMMIT.txt")

# --- 3. link into the env
$conda = $env:CONDA_EXE
if (-not $conda) {
    foreach ($base in @("$env:LOCALAPPDATA\miniconda3", "$env:USERPROFILE\miniconda3", "$env:USERPROFILE\anaconda3",
                        "$env:LOCALAPPDATA\anaconda3", "C:\ProgramData\miniconda3", "C:\ProgramData\anaconda3",
                        "$env:USERPROFILE\miniforge3")) {
        if (Test-Path "$base\Scripts\conda.exe") { $conda = "$base\Scripts\conda.exe"; break }
    }
}
if (-not $conda) { throw "conda not found" }
$prefix = (& $conda run -n $EnvName python -c "import sys; print(sys.prefix)").Trim()
$site = Join-Path $prefix "Lib\site-packages"
Set-Content -Encoding ascii -Path (Join-Path $site "gmr_k_humanoid.pth") -Value $destFull
Write-Host "linked: $site\gmr_k_humanoid.pth -> $destFull"

& $conda run -n $EnvName python -c "import general_motion_retargeting as g; print('import ok:', g.__file__)"
if ($LASTEXITCODE -ne 0) { throw "GMR import failed (are the environment.yml deps installed? run scripts\setup_env.ps1)" }
