<#
.SYNOPSIS
  Rebuild data\retargeted and reports\ with the current pipeline (docs\data.md lists what each holds).

.DESCRIPTION
  Stages (default: all four, in this order):
    retarget  data\raw -> data\retargeted\<source>\ with the recommended settings
              (--smooth 6 --swing-clearance 2). A few minutes.
    reports   reports\qc\ (QC + valid hours, C3D marker QC) and reports\compare\ (formats side by side).
              No Isaac. A few minutes (the comparison retargets through data\cache\retarget).
    isaac     reports\sim_check\, reports\physics\ (+ summary.md) and reports\videos\ with Isaac Sim's
              own python.bat. About 30 minutes. Needs the NVIDIA Omniverse EULA accepted: pass
              -IsaacAcceptEula only if you (the user) have accepted it.
    policy    reports\policy\: balance on / off in MuJoCo - the CMU clips (swing 0 and 2 cm) and LAFAN1
              with no controller and with the GMT tracking policy (tools\policy_replay.py). Needs
              scripts\install_gmt.ps1 (skipped with a warning without it). About 10 minutes.

  Run inside the k-humanoid env (conda activate k-humanoid). Licence-gated inputs (AMASS, LAFAN1,
  Unitree csv, the SMPL-X model) are used when present; their outputs stay internal (docs\data.md).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\refresh_reports.ps1 -Stage retarget,reports
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\refresh_reports.ps1 -Stage isaac -IsaacAcceptEula
#>
param(
    [string[]] $Stage = @("retarget", "reports", "isaac", "policy"),
    [string] $Python = "python",
    [string] $IsaacPython = "C:\isaacsim\python.bat",
    [string] $SmplModelDir = "models",
    [switch] $IsaacAcceptEula
)

$ErrorActionPreference = "Stop"
# "powershell -File ... -Stage retarget,reports" passes one string "retarget,reports": split it here
$Stage = @($Stage | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($s in $Stage) { if ($s -notin @("retarget", "reports", "isaac", "policy")) { throw "unknown stage '$s' (retarget, reports, isaac, policy)" } }
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Recommended = @("--smooth", "6", "--swing-clearance", "2")
$Cmu = @("02_01", "02_03", "143_11", "143_13", "143_28", "16_17")
$AmassSubject = @{ "02_01" = "02"; "02_03" = "02"; "143_11" = "143"; "143_13" = "143"; "143_28" = "143" }  # 16_17 is not in AMASS
$Lafan = @("dance1_subject1", "fallAndGetUp1_subject1", "run1_subject2", "walk1_subject1")
$PhysicsClips = @("02_01", "143_11", "143_28")

function Run([string] $exe, [string[]] $argv) {
    Write-Host ">> $exe $($argv -join ' ')"
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "failed (exit $LASTEXITCODE): $exe $($argv -join ' ')" }
}

function AmassFile([string] $clip) { "data\raw\amass_cmu_smplx\CMU\$($AmassSubject[$clip])\$($clip)_stageii.npz" }

$HaveAmass = (Test-Path (AmassFile "02_01")) -and (Test-Path (Join-Path $SmplModelDir "smplx\SMPLX_NEUTRAL.npz"))
$HaveLafan = Test-Path "data\raw\lafan1_bvh\walk1_subject1.bvh"
$HaveUnitree = Test-Path "data\raw\unitree_lafan1_g1\walk1_subject1.csv"

function Isaac([string[]] $argv, [string] $expect) {
    # a failed Isaac run must not pass for a stale result: the expected file has to be written by this run
    $t0 = Get-Date
    Run $IsaacPython (@("tools\isaac_replay.py") + $argv)
    $f = Get-Item $expect -ErrorAction SilentlyContinue
    if (-not $f -or $f.LastWriteTime -lt $t0) { throw "isaac_replay did not write $expect" }
}

if ($Stage -contains "retarget") {
    Write-Host "== retarget: data\raw -> data\retargeted (smooth 6 Hz, swing feet >= 2 cm)"
    Run $Python (@("tools\retarget.py", "data\raw\cmu_bvh", "--out-dir", "data\retargeted\cmu_bvh", "--overwrite") + $Recommended)
    Run $Python (@("tools\retarget.py", "data\raw\cmu_fbx", "--out-dir", "data\retargeted\cmu_fbx", "--overwrite") + $Recommended)
    if ($HaveAmass) {
        $files = $AmassSubject.Keys | Sort-Object | ForEach-Object { AmassFile $_ }
        Run $Python (@("tools\retarget.py") + $files + @("--smpl-model-dir", $SmplModelDir, "--out-dir",
                     "data\retargeted\amass_cmu_smplx", "--overwrite") + $Recommended)
    }
    if ($HaveLafan) {
        Run $Python (@("tools\retarget.py", "data\raw\lafan1_bvh", "--out-dir", "data\retargeted\lafan1_bvh", "--overwrite") + $Recommended)
    }
}
# data\retargeted\<the data\raw folder it came from>
$Retargeted = @("data\retargeted\cmu_bvh", "data\retargeted\cmu_fbx")
if ($HaveAmass) { $Retargeted += "data\retargeted\amass_cmu_smplx" }
if ($HaveLafan) { $Retargeted += "data\retargeted\lafan1_bvh" }

if ($Stage -contains "reports") {
    Write-Host "== reports: QC and format comparison"
    $urdf = (& $Python -c "from khumanoid import paths; print(paths.robot_urdf())").Trim()
    Run $Python @("tools\qc_report.py", "data\samples", "--out", "reports\qc\samples")
    # public KPI: one format per take for the human hours (CMU BVH), robot = the CMU retargets
    Run $Python @("tools\qc_report.py", "data\raw\cmu_bvh", "data\retargeted\cmu_bvh", "data\retargeted\cmu_fbx",
                  "--urdf", $urdf, "--balance", "--out", "reports\qc\cmu_public")
    $internal = @("data\raw\cmu_bvh")
    if ($HaveLafan) { $internal += "data\raw\lafan1_bvh" }
    if ($HaveUnitree) { $internal += "data\raw\unitree_lafan1_g1" }
    Run $Python (@("tools\qc_report.py") + $internal + $Retargeted + @("--urdf", $urdf, "--balance",
                 "--smpl-model-dir", $SmplModelDir, "--out", "reports\qc\internal"))
    # raw C3D marker QC through the CLI (stdout is one JSON object; cmd keeps the bytes as UTF-8)
    $c3d = (Get-ChildItem data\raw\cmu_c3d -Filter *.c3d | ForEach-Object { "`"$($_.FullName)`"" }) -join " "
    Write-Host ">> retlens_cli.py c3d-qc data\raw\cmu_c3d\*.c3d"
    cmd /c "`"$Python`" tools\retlens_cli.py --pretty c3d-qc $c3d > reports\qc\cmu_c3d_markers.json"
    if ($LASTEXITCODE -ne 0) { throw "c3d-qc failed" }

    New-Item -ItemType Directory -Force reports\compare | Out-Null
    $groups = @()
    foreach ($c in $Cmu) {
        $groups += @("-g", "data\raw\cmu_bvh\$c.bvh", "data\raw\cmu_fbx_from_bvh\$c.fbx", "data\raw\cmu_fbx\$c.fbx")
        if ($HaveAmass -and $AmassSubject.ContainsKey($c)) { $groups += AmassFile $c }
    }
    Run $Python (@("tools\compare_report.py", "--swing-clearance", "2", "--smpl-model-dir", $SmplModelDir) + $groups +
                 @("--out", "reports\compare\cmu_bvh_fbx_smplx.md"))
    if ($HaveLafan -and $HaveUnitree) {
        $groups = @()
        foreach ($c in $Lafan) { $groups += @("-g", "data\raw\lafan1_bvh\$c.bvh", "data\raw\unitree_lafan1_g1\$c.csv") }
        Run $Python (@("tools\compare_report.py", "--swing-clearance", "2") + $groups + @("--out", "reports\compare\lafan1_gmr_vs_unitree.md"))
    }
}

if ($Stage -contains "isaac") {
    if (-not $IsaacAcceptEula) {
        throw "the isaac stage needs the NVIDIA Omniverse EULA: pass -IsaacAcceptEula only if you accepted it"
    }
    if (-not (Test-Path $IsaacPython)) { throw "Isaac Sim not found: $IsaacPython (-IsaacPython <...\python.bat>)" }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Write-Warning "ffmpeg is not on PATH: videos come out as GIF" }
    $env:OMNI_KIT_ACCEPT_EULA = "YES"
    Write-Host "== isaac: kinematic check + video (CMU BVH)"
    foreach ($c in $Cmu) {
        Isaac @("--human", "data\raw\cmu_bvh\$c.bvh", "--robot-motion", "data\retargeted\cmu_bvh\$($c)_g1.npz",
                "--video", "reports\videos\kinematic\$c.mp4", "--check-out", "reports\sim_check") "reports\sim_check\$($c)_sim_check.json"
    }
    Write-Host "== isaac: physics (harness x1) + video, 3 clips x 3 sources"
    foreach ($c in $PhysicsClips) {
        $runs = @(@{ src = "cmu_bvh"; robot = "data\retargeted\cmu_bvh\$($c)_g1.npz"; human = @("--human", "data\raw\cmu_bvh\$c.bvh") },
                  # FBX: Isaac draws the same take's BVH skeleton (it reads no FBX)
                  @{ src = "cmu_fbx"; robot = "data\retargeted\cmu_fbx\$($c)_g1.npz"; human = @("--human", "data\raw\cmu_bvh\$c.bvh") })
        if ($HaveAmass) {
            $runs += @{ src = "amass_cmu_smplx"; robot = "data\retargeted\amass_cmu_smplx\$($c)_stageii_g1.npz";
                        human = @("--human", (AmassFile $c), "--smpl-model-dir", $SmplModelDir) }
        }
        foreach ($r in $runs) {
            $stem = [IO.Path]::GetFileNameWithoutExtension($r.robot)
            Isaac ($r.human + @("--robot-motion", $r.robot, "--physics", "--check-out", "reports\physics\$($r.src)",
                                "--video", "reports\videos\physics\$($c)_$($r.src).mp4")) "reports\physics\$($r.src)\$($stem)_sim.json"
        }
    }
    if ($HaveLafan) {
        Write-Host "== isaac: internal LAFAN1 video (20 s of dance1)"
        Isaac @("--human", "data\raw\lafan1_bvh\dance1_subject1.bvh", "--robot-motion", "data\retargeted\lafan1_bvh\dance1_subject1_g1.npz",
                "--video", "reports\videos\internal_lafan1\dance1_30-50s.mp4", "--start", "30", "--end", "50") "reports\videos\internal_lafan1\dance1_30-50s.mp4"
    }
    $folders = @("cmu_bvh", "cmu_fbx", "amass_cmu_smplx") | ForEach-Object { "reports\physics\$_" } | Where-Object { Test-Path $_ }
    Run $Python (@("tools\physics_report.py") + $folders + @("--out", "reports\physics\summary.md"))
}

if ($Stage -contains "policy") {
    $gmt = if ($env:KHUMANOID_GMT_DIR) { $env:KHUMANOID_GMT_DIR } else { Join-Path (Split-Path -Parent $Root) "GMT" }
    if (-not (Test-Path (Join-Path $gmt "assets\pretrained_checkpoints\pretrained.pt"))) {
        Write-Warning "GMT not found in $gmt (scripts\install_gmt.ps1): policy stage skipped"
    } else {
        Write-Host "== policy: balance on / off in MuJoCo (no controller vs the GMT tracking policy)"
        $cmu = @("data\raw\cmu_bvh", "data\raw\cmu_fbx")
        if ($HaveAmass) { $cmu += $AmassSubject.Keys | Sort-Object | ForEach-Object { AmassFile $_ } }
        foreach ($s in @("0", "2")) {
            Run $Python (@("tools\policy_replay.py") + $cmu + @("--swing-clearance", $s, "--video", "--out-dir", "reports\policy\swing$s"))
        }
        if ($HaveLafan) {
            $lafan = @("data\raw\lafan1_bvh")
            if ($HaveUnitree) { $lafan += "data\raw\unitree_lafan1_g1" }
            Run $Python (@("tools\policy_replay.py") + $lafan + @("--swing-clearance", "2", "--out-dir", "reports\policy\lafan1"))
        }
        Run $Python @("tools\policy_replay.py", "--summary", "reports\policy")
    }
}
Write-Host "done"
