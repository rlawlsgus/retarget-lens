<#
.SYNOPSIS
  Zip the built RetLens folder for a GitHub release: dist\RetLens-<version>-win64.zip + .sha256.

.DESCRIPTION
  Run after scripts\build_retlens.ps1. The version comes from retlens\__init__.py (__version__);
  the built retlens-cli.exe must report the same one, so a stale build is not shipped by mistake.
  The zip holds one top folder, RetLens\ (RetLens.exe, retlens-cli.exe, _internal\). Upload the zip
  and the .sha256 file to the release.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1
#>
param(
    [string] $Dist = "dist\RetLens",
    [string] $OutDir = "dist",
    [switch] $Force  # replace an existing zip of the same version
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$init = Get-Content retlens\__init__.py -Raw
if ($init -notmatch '__version__\s*=\s*"([^"]+)"') { throw "__version__ not found in retlens\__init__.py" }
$version = $Matches[1]

$exe = Join-Path $Dist "RetLens.exe"
$cli = Join-Path $Dist "retlens-cli.exe"
foreach ($f in @($exe, $cli)) {
    if (-not (Test-Path $f)) { throw "$f not found: build first (scripts\build_retlens.ps1 -Samples)" }
}

# the build must be of this version (the CLI prints one JSON object on stdout, progress on stderr)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Continue"  # Windows PowerShell turns a native program's stderr into errors
$info = & $cli info 2>$null | Out-String
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($code -ne 0) { throw "retlens-cli.exe info failed (exit $code): the build does not run" }
$built = ($info | ConvertFrom-Json).version
if ($built -ne $version) { throw "the build reports version '$built' but retlens\__init__.py says ${version}: rebuild" }

New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$zip = Join-Path $OutDir "RetLens-$version-win64.zip"
if (Test-Path $zip) {
    if (-not $Force) { throw "$zip exists (pass -Force to replace it)" }
    Remove-Item $zip
}
Write-Host "zipping $Dist -> $zip"
# entries one by one with "/" separators: ZipFile.CreateFromDirectory under Windows PowerShell 5.1 writes
# "RetLens\RetLens.exe", which Explorer accepts but the zip format (and other unzip tools) do not
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$src = (Resolve-Path $Dist).Path
$top = Split-Path $src -Leaf
$stream = [IO.File]::Open((Join-Path (Resolve-Path $OutDir).Path (Split-Path $zip -Leaf)), [IO.FileMode]::CreateNew)
$archive = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($f in Get-ChildItem $src -Recurse -File) {
        $entry = $top + "/" + $f.FullName.Substring($src.Length + 1).Replace("\", "/")
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $f.FullName, $entry,
                                                                [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $archive.Dispose()
    $stream.Dispose()
}

$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
$name = Split-Path $zip -Leaf
[IO.File]::WriteAllText((Join-Path (Resolve-Path $OutDir).Path "$name.sha256"), "$hash  $name`n", (New-Object Text.UTF8Encoding $false))

$mb = (Get-Item $zip).Length / 1MB
Write-Host ("{0}  {1:N0} MB  sha256 {2}" -f $name, $mb, $hash)
if ((Get-Item $zip).Length -ge 2GB) { Write-Warning "GitHub release assets must be under 2 GiB: split the zip or shrink the build" }
Write-Host "upload both files: $zip, $zip.sha256 "
