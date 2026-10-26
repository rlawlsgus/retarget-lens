<#
.SYNOPSIS
  Download GMT (General Motion Tracking, Apache-2.0) - a pretrained G1 whole-body tracking policy -
  for tools\policy_replay.py, without git.

.DESCRIPTION
  Downloads a pinned commit of github.com/zixuan417/humanoid-general-motion-tracking, but only what
  the MuJoCo replay needs (about 30 MB instead of the 70 MB tree with images):
    LICENSE, README.md, sim2sim.py, view_motion.py, utils/  (the reference implementation)
    assets/pretrained_checkpoints/pretrained.pt              (TorchScript policy, 23 DoF)
    assets/robots/g1/g1.xml + README.md + the meshes g1.xml uses
    assets/motions/*.pkl                                      (the authors' example motions)
  Every file is checked against its git blob SHA-1 from the commit's tree.

  The README says the provided model is for research use only. Nothing is linked into the conda env:
  tools\policy_replay.py reads the files from the folder (default ..\GMT next to the project).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_gmt.ps1
#>
param(
    [string]$Dest = "",
    [string]$Commit = "2a590de25a1eb08e47491977a738549c22f16e1f"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar on
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Dest) { $Dest = Join-Path (Split-Path -Parent $ProjectRoot) "GMT" }
$Repo = "zixuan417/humanoid-general-motion-tracking"

function Get-GitBlobSha1([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $header = [System.Text.Encoding]::ASCII.GetBytes("blob $($bytes.Length)`0")
    $sha = [System.Security.Cryptography.SHA1]::Create()
    $sha.TransformBlock($header, 0, $header.Length, $null, 0) | Out-Null
    $sha.TransformFinalBlock($bytes, 0, $bytes.Length) | Out-Null
    return ([System.BitConverter]::ToString($sha.Hash) -replace "-", "").ToLower()
}

function Get-Verified($item, [string]$root) {
    if ($item.path -match '(^|/)\.\.(/|$)' -or $item.path -match '^[/\\]' -or $item.path -match ':') { throw "unsafe path in tree: $($item.path)" }
    $out = Join-Path $root ($item.path -replace "/", "\")
    if ((Test-Path $out) -and (Get-GitBlobSha1 $out) -eq $item.sha) { return $false }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/$Repo/$Commit/$($item.path)" -OutFile $out -UseBasicParsing -TimeoutSec 120
    if ((Get-GitBlobSha1 $out) -ne $item.sha) { Remove-Item $out; throw "SHA-1 mismatch: $($item.path)" }
    return $true
}

Write-Host "GMT $Repo@$($Commit.Substring(0, 7)) -> $Dest"
$tree = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/git/trees/$Commit`?recursive=1" -TimeoutSec 60
if ($tree.truncated) { throw "GitHub returned a truncated tree; cannot verify the file list" }
$blobs = @{}
foreach ($item in $tree.tree) { if ($item.type -eq "blob") { $blobs[$item.path] = $item } }

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$root = (Resolve-Path $Dest).Path

# the robot model first: its mesh list decides which meshes to fetch
$xml = "assets/robots/g1/g1.xml"
if (-not $blobs.ContainsKey($xml)) { throw "no $xml in GMT@$Commit" }
[void](Get-Verified $blobs[$xml] $root)
$meshes = Select-String -Path (Join-Path $root ($xml -replace "/", "\")) -Pattern 'file="([^"]+)"' -AllMatches |
    ForEach-Object { $_.Matches } | ForEach-Object { "assets/robots/g1/meshes/" + $_.Groups[1].Value } | Sort-Object -Unique

$wanted = @("LICENSE", "README.md", "sim2sim.py", "view_motion.py", "assets/pretrained_checkpoints/pretrained.pt",
            "assets/robots/g1/README.md") + $meshes
$wanted += $blobs.Keys | Where-Object { $_ -like "utils/*.py" -or $_ -like "assets/motions/*.pkl" }
$missing = $wanted | Where-Object { -not $blobs.ContainsKey($_) }
if ($missing) { throw "not in GMT@${Commit}: $($missing -join ', ')" }
$totalMB = ($wanted | ForEach-Object { $blobs[$_].size } | Measure-Object -Sum).Sum / 1MB
Write-Host ("{0} files, {1:N1} MB" -f ($wanted.Count + 1), $totalMB)

$n = 0
foreach ($p in $wanted) { if (Get-Verified $blobs[$p] $root) { $n++ } }
Write-Host "downloaded $n file(s), all $($wanted.Count + 1) verified"
@"
repo: https://github.com/$Repo
commit: $Commit
license: Apache-2.0 (LICENSE); README: the provided model is for research use only
installed_by: RetLens scripts\install_gmt.ps1 (partial checkout, not a git clone)
"@ | Set-Content -Encoding ascii (Join-Path $root "GMT_COMMIT.txt")
