<#
.SYNOPSIS
  Install Isaac Sim (standalone zip) globally, outside the project folder.

.DESCRIPTION
  Downloads the official Windows zip from NVIDIA (skipped when a verified copy is
  already in Downloads), checks its MD5, extracts it to C:\isaacsim and runs
  post_install.bat. Re-running is safe.

  Requirements (Isaac Sim 6.1): Windows 11, NVIDIA driver >= 595.97,
  RTX GPU (16 GB VRAM officially; 8 GB works for single-robot scenes), ~25 GB disk.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_isaacsim.ps1
#>
param(
    [string]$Version = "6.1.0",
    [string]$InstallDir = "C:\isaacsim",
    [string]$Md5 = "a07968e980072c9ca27b2166443e2d89",  # from the 6.1.0 download page
    [string]$DownloadDir = (Join-Path $env:USERPROFILE "Downloads")
)
$ErrorActionPreference = "Stop"

$zipName = "isaac-sim-standalone-$Version-windows-x86_64.zip"
$url = "https://downloads.isaacsim.nvidia.com/$zipName"
$zip = Join-Path $DownloadDir $zipName

function Test-Zip {
    if (-not (Test-Path $zip)) { return $false }
    Write-Host "Verifying MD5 of $zip ..."
    $h = (Get-FileHash -Algorithm MD5 $zip).Hash.ToLower()
    if ($h -ne $Md5.ToLower()) { Write-Warning "MD5 mismatch ($h)"; return $false }
    return $true
}

# 1. driver check (warn only)
try {
    $drv = (& nvidia-smi --query-gpu=driver_version --format=csv,noheader | Select-Object -First 1).Trim()
    if ([version]$drv -lt [version]"595.97") {
        Write-Warning "NVIDIA driver $drv < 595.97 (tested driver for Isaac Sim 6.x). Update it from https://www.nvidia.com/Download/index.aspx"
    } else { Write-Host "NVIDIA driver $drv OK" }
} catch { Write-Warning "nvidia-smi not found: is an NVIDIA driver installed?" }

# 2. download (resumable) unless a verified zip already exists
if (-not (Test-Zip)) {
    Write-Host "Downloading $url (~10 GB) ..."
    & curl.exe -L --fail --retry 5 --retry-delay 5 -C - -o $zip $url
    if ($LASTEXITCODE -ne 0) { throw "download failed (curl exit $LASTEXITCODE)" }
    if (-not (Test-Zip)) { throw "downloaded file failed MD5 verification; delete $zip and retry" }
}

# 3. extract
if (Test-Path (Join-Path $InstallDir "isaac-sim.bat")) {
    Write-Host "Isaac Sim already extracted at $InstallDir (delete the folder to reinstall)."
} else {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Write-Host "Extracting to $InstallDir (several minutes) ..."
    & tar.exe -xf $zip -C $InstallDir
    if ($LASTEXITCODE -ne 0) { throw "extraction failed (tar exit $LASTEXITCODE)" }
}

# 4. post-install: symlinks the GUI extension examples. mklink /D needs admin or
#    Windows developer mode; the simulator works fine without it.
& cmd.exe /c "`"$InstallDir\post_install.bat`""
if ($LASTEXITCODE -ne 0) { Write-Warning "post_install.bat failed (optional: only links extension_examples)" }

Write-Host ""
Write-Host "Isaac Sim $Version installed at $InstallDir"
Write-Host "  GUI:            $InstallDir\isaac-sim.bat   (first start compiles shaders: 5-15 min)"
Write-Host "  Python scripts: $InstallDir\python.bat your_script.py"
Write-Host "  Project env:    powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1"
