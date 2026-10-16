# K-Humanoid — Human MoCap 데이터셋 도구

K-온디바이스 휴머노이드 과제의 1차년도 산출물인 **Human MoCap 기반 전신 모션 데이터셋**을 모으고 검증하기 위한 작업 폴더입니다.
아직 Task–Subtask 정의 전이라, 지금 있는 것은 아래 네 가지입니다.

1. **사전 조사**: 모캡 데이터 포맷, 공개 데이터셋(라이선스 포함), 배우용 레퍼런스 영상, 리타게팅 툴 → [docs/research/mocap_survey.md](docs/research/mocap_survey.md)
2. **QC와 유효시간 집계**: 모캡 파일을 프레임 단위로 검사해 "유효 데이터 시간"을 합산합니다(목표 5 h). → `tools/qc_report.py`
3. **리타게팅**: 사람 모캡(BVH, FBX, AMASS SMPL-X)을 GMR로 Unitree G1(29 DoF)에 옮겨 프로젝트 표준 로봇 npz로 저장합니다. → `tools/retarget.py`
4. **Isaac Sim 재현과 물리 검증**: 사람 모캡(스틱 피겨)과 리타게팅된 로봇 모션을 Isaac Sim에서 나란히 재생합니다. `--physics`를 주면 중력·바닥 접촉·관절 PD로 실제 물리 시뮬레이션을 돌려 물리 정합성을 잽니다. → `tools/isaac_replay.py`
5. **비교 뷰어**: 여러 포맷을 같은 G1에 올려 브라우저에서 나란히 보고 수치로 비교합니다(SMPL-X 몸 메시, Isaac 물리 결과 포함). → `tools/compare_viewer.py`, `tools/compare_report.py`

공개 샘플(CMU BVH, LAFAN1, Unitree G1 csv)로 위 과정을 끝까지 돌려 확인했습니다(2026-10-15, 아래 "실데이터 점검").

## 설치

버전·드라이버·하드웨어·네트워크 요구사항과 정확한 재현용 잠금 파일(`environment.lock.txt`)은 [requirements.md](requirements.md)에 정리했습니다.

### 1) Isaac Sim 6.1.0: 전역 설치 (`C:\isaacsim`)

프로젝트 폴더가 아닌 `C:\isaacsim`에 설치해 다른 프로젝트와 공유합니다. 이 PC에는 이미 설치되어 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_isaacsim.ps1
```

- 스크립트가 하는 일: NVIDIA 공식 zip(10.4 GB)을 받아 MD5를 확인하고, `C:\isaacsim`에 압축을 풀고, `post_install.bat`을 실행합니다.
- `post_install.bat`은 GUI 예제 링크만 만듭니다. 관리자 권한이 없으면 실패하지만 무시해도 됩니다.
- **NVIDIA 드라이버 595.97 이상**이 필요합니다(6.x 테스트 드라이버). 이 PC는 617.42입니다.
- 공식 최소 사양은 RTX 4080 / 16 GB입니다. 이 PC의 RTX 3070 8 GB는 미달이지만, 로봇 1대와 스틱 피겨를 재생하는 데는 문제없었습니다.
- 첫 실행은 셰이더 컴파일 때문에 약 2분 걸리고, 이후에는 약 20초 걸립니다.
- 처음 실행할 때 NVIDIA 라이선스(EULA) 동의를 묻습니다. 무인 실행에서는 `OMNI_KIT_ACCEPT_EULA=YES`로 동의합니다.

### 2) conda 환경 `k-humanoid`

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1
conda activate k-humanoid
```

- [environment.yml](environment.yml)로 환경을 만듭니다. Python 3.12, numpy 2.3, scipy 1.17로 Isaac Sim 6.1 내장 버전과 맞춰 고정되어 있습니다.
- activate 훅이 `C:\isaacsim`을 연결합니다. 그래서 env 안의 `python`에서 바로 `from isaacsim import SimulationApp`이 됩니다. Isaac Sim 파일은 env에 복사되지 않습니다.
- 이 네트워크는 Anaconda `defaults` 채널이 막혀 있어(HTTP 429, 클라이언트 등록 필요) conda-forge만 씁니다.
- 마지막에 아래 3)의 GMR 설치까지 실행합니다(`-SkipGmr`로 생략).

### 3) GMR 리타게터 (`..\GMR`, 프로젝트 폴더 밖)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_gmr.ps1
```

- [GMR](https://github.com/YanjieZe/GMR)(MIT)은 패키지 인덱스에 없어서, 고정 커밋(`bb1bbe4`)에서 코드와 `assets/unitree_g1`만 받습니다(약 53 MB, 전체 트리는 1.2 GB). 파일마다 git blob SHA-1을 확인합니다.
- 받은 폴더(`C:\Users\<user>\Documents\Github\GMR`)를 env의 `gmr_k_humanoid.pth`로 연결합니다(`pip install -e`와 같은 효과, git·빌드 도구 불필요).
- GMR 의존성은 environment.yml에 있습니다. conda-forge: mujoco-python 3.11.0(Isaac Sim 내장 버전과 동일), qpsolvers+daqp, pytorch CPU 등 약 92 MB. PyPI: mink 1.3.0(conda-forge에 없음), smplx 0.1.28.
- GMR은 import할 때 torch를 요구합니다. `smplx` 코드는 MPI 비상업 연구 라이선스이고 SMPL-X 경로에만 씁니다.
- env에 torch가 생기면 `from isaacsim import SimulationApp`이 Kit 시작 전에 env의 torch와 numpy를 불러와 Isaac 확장이 깨집니다(numpy.fft DLL 오류). `tools/isaac_replay.py`는 그 import 동안만 torch를 숨겨 해결했습니다. 다른 Isaac 스크립트를 이 env에서 돌릴 때도 같은 처리가 필요합니다.

### 4) Blender 4.5 LTS: FBX 읽기용 (`C:\blender`, 프로젝트 폴더 밖)

FBX는 Autodesk 비공개 포맷이라 Blender의 FBX 임포터로 읽습니다. 설치 프로그램 없이 공식 zip을 풀기만 합니다.

```powershell
# download.blender.org/release/Blender4.5/blender-4.5.14-windows-x64.zip (380 MB, sha256 b9533d23…c8b9)
Expand-Archive blender-4.5.14-windows-x64.zip -DestinationPath C:\blender
```

- `khumanoid/io/fbx.py`가 `$BLENDER` → `C:\blender\*\blender.exe` → PATH 순서로 찾습니다. 다른 곳에 풀었으면 `BLENDER=<blender.exe 경로>`를 설정하세요.
- 클립마다 Blender를 헤드리스로 띄워(약 2초) 관절 궤적을 뽑고 `data/cache/fbx/`에 캐시합니다. BVH·SMPL-X만 쓰면 Blender는 필요 없습니다.
- 처음에는 PyPI `ufbx` 0.0.5(파이썬 바인딩)를 시험했지만, 노드 부모를 읽을 때 접근 위반으로 죽거나 틀린 값을 돌려줘 쓰지 않습니다(바인딩 이슈 #12와 같은 증상).

## 사용법

```powershell
conda activate k-humanoid

# 동작 확인용 합성 샘플 생성 (data/samples/): 사람 BVH(정상/글리치), G1 로봇 npz/csv
python tools\make_samples.py

# 공개 샘플 받기 (data/raw/, 출처·라이선스는 각 폴더의 SOURCE.md)
python tools\fetch_samples.py                  # cmu, unitree, lafan1 전부 (약 150 MB 다운로드, 남는 건 약 30 MB)
python tools\fetch_samples.py cmu              # CMU BVH 6개만 (2.3 MB)

# 1) 리타게팅: 사람 BVH / FBX / AMASS SMPL-X -> G1 npz (data/retargeted/<clip>_g1.npz + .json)
python tools\retarget.py data\raw\cmu_bvh --smooth 6        # 6 Hz 평활화 권장 (기본값은 끔)
python tools\retarget.py data\raw\cmu_bvh --smooth 6 --swing-clearance 2   # + 움직이는 발 바닥에서 2 cm 띄우기 (권장)
python tools\retarget.py data\raw\lafan1_bvh --out-dir data\retargeted\lafan1
python tools\retarget.py clip_stageii.npz --smpl-model-dir models   # SMPL-X 바디모델 필요
python tools\retarget.py data\raw\cmu_fbx --smooth 6 --out-dir data\retargeted\cmu_fbx_smooth6   # FBX (Blender 필요)

# 2) QC + 유효시간 집계 (Isaac Sim 불필요, 수 초)
python tools\qc_report.py data\samples --out reports\qc_samples
python tools\qc_report.py data\raw data\retargeted --urdf ..\GMR\assets\unitree_g1\g1_custom_collision_29dof.urdf --out reports\qc_real

# 3) Isaac Sim GUI 재생
python tools\isaac_replay.py --human data\samples\synthetic_walk_glitch.bvh
python tools\isaac_replay.py --robot-motion data\samples\synthetic_g1_walk.npz
python tools\isaac_replay.py --human data\raw\cmu_bvh\143_11.bvh --robot-motion data\retargeted\143_11_g1.npz

# 4) 헤드리스 배치 검사: 전체 프레임 재생 + 스냅샷 + JSON
python tools\isaac_replay.py --human data\raw\cmu_bvh\143_11.bvh --robot-motion data\retargeted\143_11_g1.npz --headless --check-out reports\sim_check

# 5) 동영상 (사람·로봇 나란히, MP4. ffmpeg가 PATH에 없으면 GIF)
python tools\isaac_replay.py --human data\raw\cmu_bvh\143_11.bvh --robot-motion data\retargeted\smooth6\143_11_g1.npz --video reports\videos\143_11.mp4
python tools\isaac_replay.py --human data\raw\lafan1_bvh\dance1_subject1.bvh --robot-motion data\retargeted\lafan1_smooth6\dance1_subject1_g1.npz --video reports\videos\internal_lafan1\dance1.mp4 --start 30 --end 50

# 6) 물리 재생 (PhysX: 중력, 마찰 바닥, 관절 PD, 골반 보조 힘) -> <clip>_sim.npz + _sim.json
python tools\isaac_replay.py --robot-motion data\retargeted\smooth6\143_11_g1.npz --physics --check-out reports\physics\smooth6
python tools\isaac_replay.py --robot-motion data\retargeted\smooth6\02_01_g1.npz --physics --assist 0     # 보조 힘 없이 (넘어지면 리셋하고 셈)
python tools\isaac_replay.py --human data\raw\cmu_bvh\143_11.bvh --robot-motion data\retargeted\smooth6\143_11_g1.npz --physics --video reports\videos\physics\143_11.mp4
```

- 로봇 npz는 숫자 배열 묶음이라 직접 열어 볼 수 없습니다. 3)의 GUI 재생(재생·일시정지·슬라이더)으로 보거나 5)처럼 동영상으로 뽑으세요. 숫자만 보려면 `python -c "import numpy as np; d = np.load('X_g1.npz'); print({k: d[k].shape for k in d})"`.
- `--video`는 헤드리스로 돌고, 카메라가 사람과 로봇의 중간을 따라갑니다. 화면 위에 클립 이름·시간·프레임과, QC에 걸린 프레임이면 "QC flag"가 찍힙니다. 검사 JSON과 스냅샷은 비디오와 같은 폴더에 저장됩니다(`--check-out`으로 변경).

- 유효시간은 넘겨준 폴더 전체를 합산합니다. 공개 KPI(5 h)는 공개 가능한 데이터 폴더만 넣어 집계하세요. LAFAN1·Unitree csv는 내부 검증용입니다.

conda 없이 실행하려면 `python` 대신 `C:\isaacsim\python.bat`을 쓰면 됩니다. QC 스크립트는 pandas가 필요하므로 conda env에서 실행하세요.

**GUI 재생 창 (Mocap Replay)**
- Play/Pause, ±1프레임, 슬라이더 스크럽, 재생 속도, 카메라 따라가기를 지원합니다.
- `< bad` / `bad >` 버튼은 QC에 걸린 프레임으로 바로 이동합니다.
- QC에 걸린 프레임에서는 스틱 피겨가 **빨간색**으로 바뀝니다.

**로봇 재생**
- 기본은 매 프레임 루트 자세와 관절각을 텔레포트하는 kinematic replay입니다. 중력은 끄고, 바닥은 충돌 없는 시각용입니다. 관통을 해소하지 않고 그대로 보여주기 위해서입니다. 물리 시뮬레이션은 `--physics`입니다(아래 "Isaac 물리 재생").
- 기본 로봇은 Isaac Sim 에셋 서버의 **Unitree G1(29 DoF + 손)**입니다. LG 휴머노이드 에셋이 오기 전까지 대용으로 쓰며, 이후 `--robot-usd`로 교체합니다.
- 관절은 이름으로 매칭합니다. 모션에 없는 로봇 관절(예: 손가락)은 0으로 둡니다.

**헤드리스 검사 결과** (`<clip>_sim_check.json`, PNG)
- 사람 QC와 로봇 QC 결과가 들어갑니다. 로봇 QC의 관절한계는 로봇 에셋에서 직접 읽습니다.
- 시뮬레이터에서 측정한 발바닥 높이로 관통 비율, 양발 공중 비율, 발 미끄러짐 비율을 계산합니다.
- 스냅샷은 클립 전체에서 고르게 뽑은 프레임과, QC에 걸린 구간의 중간 프레임입니다.
- QC 임계값은 `configs/qc.yaml`을 읽습니다(`--qc-config`).
- 로봇 발 지표는 로봇 프레임마다 한 번씩 셉니다. 재생 시계는 더 빠른 클립(사람 120 fps)을 따르므로, 30 fps 로봇 자세가 4번씩 반복되기 때문입니다.
- 발 미끄러짐은 발바닥 전체가 바닥에 붙은 상태(발 박스 아랫면 네 꼭짓점이 모두 2.5 cm 이내)에서 0.3 m/s보다 빠르게 0.1 s 이상 미끄러진 비율입니다. 최저점만 보면 스윙 중 발끝 스침까지 접지로 셉니다(CMU 리타겟에서 39% vs 0.8%).
- **균형(`robot_balance`)**: 계산은 `khumanoid/stability.py`에 있고, 뷰어와 `qc_report.py --balance`는 같은 코드를 GMR MJCF 질량으로 씁니다.
  - **질량중심(CoM):** 로봇 에셋의 링크 질량·질량중심(`Articulation.get_link_masses / get_link_coms`, G1 34.24 kg, 링크 46개)과 매 프레임 링크 자세로 구합니다.
  - **ZMP:** cart-table 근사입니다. `zmp = com_xy − (com_z − 바닥)/(g + com_z'') · com_xy''`이고, CoM을 6 Hz로 평활한 뒤 두 번 미분합니다. 각운동량 항은 넣지 않았습니다.
  - **지지다각형:** 바닥(디딤발 높이를 따라간 값) 2 cm 안에 있는 발바닥 충돌 상자 꼭짓점들의 볼록껍질입니다. 양발/한발/공중을 나누고, 공중 프레임은 여유 계산에서 뺍니다.
  - **지표:** CoM 투영과 ZMP 각각에 대해 다각형 경계까지의 부호 있는 거리(여유, m, +는 안쪽), 다각형 밖 프레임 비율(2 cm 넘게 0.1 s 이상 밖 비율 포함), 최악 시각, 가장 긴 이탈 구간을 냅니다.
  - **QC soft 플래그 `static_unbalanced`:** 몸이 거의 멈춰 있는데(CoM < 0.1 m/s) CoM 투영이 지지다각형 밖 2 cm 넘게 0.2 s 이상 있는 프레임입니다(아래 "검증(QC) 기준").
  - **주의:** 걷는 중의 CoM/ZMP "밖" 비율은 무엇을 지지로 세느냐에 민감합니다. 스윙 발 보정 뒤 02_01 SMPL-X 리타겟의 CoM 밖 비율이 9% → 38%로 올랐습니다. 바닥에 끌리던 스윙 발이 2 cm 위로 들려 지지다각형에서 빠졌기 때문이고, 정적 불균형은 0% 그대로입니다. 그래서 QC에는 정적 조건만 씁니다.

## 리타게팅 (사람 → G1)

`tools/retarget.py`(본체는 `khumanoid/retarget.py`)가 GMR의 프레임별 differential IK(mink + MuJoCo)로 G1 29 DoF 관절각을 풉니다. CPU에서 초당 170~230 프레임입니다.

| 입력 (`--format auto`가 고름) | 처리 |
|---|---|
| `tpose`: T-pose 기준 BVH (CMU cgspeed 변환본, Vicon/OptiTrack/Xsens/Rokoko 내보내기) | GMR에 이 스켈레톤용 설정이 없어 클립마다 만듭니다(아래). CMU는 변환기가 넣은 0번 T-pose 프레임을 기준으로 쓰고 출력에서는 뺍니다. 그 밖의 파일은 rest pose가 기준입니다(`--ref <frame>`으로 변경) |
| `fbx`: FBX 스켈레톤 애니메이션 (MotionBuilder, Shogun, Motive, MVN, Mixamo, Blender 내보내기) | Blender로 읽은 뒤 `tpose`와 같은 방법으로 설정을 만듭니다. 기준은 아마추어의 rest pose입니다. cgspeed CMU 변환본처럼 0번 프레임이 rest pose(T-pose)이고 다음 프레임부터 동작이면 그 프레임을 기준으로 쓰고 뺍니다(`--ref <frame>`으로 변경). 관절 이름은 MotionBuilder/Mixamo(`mixamorig:` 접두사), Daz(`lThigh`), Motive(`Skeleton1_` 접두사) 표기를 인식합니다 |
| `lafan1` / `nokov` | GMR 자체 BVH 로더와 IK 설정을 그대로 씁니다 |
| `smplx`: AMASS SMPL / SMPL-X npz | `tpose`와 같은 방법으로 설정을 만듭니다. 바디모델의 zero pose가 T-pose라 그대로 적용되고, 같은 클립의 BVH 결과와 바로 비교할 수 있습니다. SMPL-X 바디모델(`models/smplx/`)이 필요합니다 |
| `smplx-gmr` | 같은 파일을 GMR 자체 SMPL-X 로더·설정으로 처리합니다. 로봇 발끝 링크를 SMPL-X 발가락 관절에 맞춰서, AMASS CMU에서는 발이 3–5 cm 기울어 바닥을 뚫습니다(아래 비교) |

T-pose 설정을 만드는 방법:
- IK 과제 목록과 가중치는 GMR의 LAFAN1→G1 설정을 그대로 씁니다. 골반·몸통·상완은 방향, 발은 위치를 중시합니다.
- 회전 오프셋: 사람 T-pose의 관절 방향과, 같은 자세로 맞춘 로봇의 링크 방향을 대응시킵니다. 로봇 자세는 먼저 어깨 roll, 팔꿈치, 고관절 roll, 무릎을 하나씩 맞춘 뒤, 팔다리마다 굽힘 관절(고관절 pitch·roll·무릎, 어깨 pitch·roll·팔꿈치)을 함께 최적화합니다. 마지막으로 발목으로 발을 수평으로 맞춥니다. 비틀림(yaw) 관절은 쓰지 않습니다. 기준 골격의 작은 꺾임을 맞추느라 75°까지 비틀어져, 모든 프레임이 틀어졌기 때문입니다.
- 위치 오프셋: G1 링크 원점이 관절 중심에 있지 않은 곳(hip_yaw_link는 허벅지 중간, shoulder_yaw_link는 상완 중간)을 보정합니다.
- 스케일(피험자별 자동): 다리·루트는 골반-발목 거리 비, 몸통·팔은 골반-손목 거리 비입니다.
- 바닥: 하위 5% 프레임에서 발이 로봇 발목 높이(발바닥 위 3.6 cm)에 오도록 전체를 내립니다.
- IK는 로봇 루트를 첫 프레임의 골반 목표로 옮긴 뒤 시작합니다. GMR 기본값(원점·정면에서 시작)으로는 반대 방향을 보고 시작하는 클립(CMU 143)에서 골반이 72° 틀어진 채로 남았습니다.

출력 (기본 30 fps, `--fps 0`이면 원본 유지):
- `<clip>_g1.npz`: 프로젝트 표준 로봇 npz. `joint_names`는 MJCF 순서이고 Unitree csv 순서와 같습니다.
- `<clip>_g1.json`: 출처, 라이선스 노트(`SOURCE.md` 경로), GMR 커밋, 생성된 IK 설정, 스케일, IK 위치 잔차, 평활화 설정(평활화 전 잔차 포함).
- `--pkl`: GMR 자체 pkl(root_rot **xyzw**, TWIST/GMT 입력용).

### 평활화 (`--smooth 6` 권장)

GMR은 프레임마다 IK를 따로 풀어서 프레임 사이 떨림이 남습니다. `--smooth HZ`는 결과에 4차 Butterworth 저역통과를 앞뒤로 한 번씩(filtfilt, 위상 지연 없음) 걸고, 관절을 MJCF 한계 안으로 다시 자릅니다. 대상은 관절각, 루트 위치, 루트 쿼터니언(부호 연속화 후 성분별 필터, 재정규화)입니다. 기본값은 꺼져 있습니다.

LAFAN1 4클립(13.3분)에서 설정별로 비교한 결과입니다(클립 평균, 기준은 Unitree 공식 리타겟):

| 설정 | 관절 가속도 (rad/s²) | 관절 저크 (rad/s³) | 최대 관절속도 (rad/s) | URDF 속도 위반 프레임 | 원본 대비 관절 변화 (RMSE) | 발 위치 변화 평균 / 최대 | 발바닥 미끄러짐 |
|---|---|---|---|---|---|---|---|
| GMR 원본 | 22.2 | 761 | 28.5 | 0.06% (춤 0.2%) | – | – | 0.20% |
| GMR `--velocity-limit` | 22.2 | 760 | 28.5 | 0.06% | 0.00° | 0 cm | 0.20% |
| **Butterworth 6 Hz** | **16.6** | **354** | **18.7** | **0%** | **0.70°** | **0.23 / 3.6 cm** | **0.45%** |
| Butterworth 8 Hz | 18.8 | 480 | 21.5 | 0.01% | 0.46° | 0.13 / 2.5 cm | 0.36% |
| Butterworth 4 Hz | 13.1 | 215 | 15.1 | 0% | 1.27° | 0.51 / 5.9 cm | 0.59% |
| Savitzky–Golay 11프레임 | 11.4 | 203 | 13.1 | 0% | 1.75° | 0.75 / 7.6 cm | 0.79% |
| Unitree 공식 리타겟 (참고) | 15.9 | 442 | 18.2 | 0% | – | – | 0.72% |

- **6 Hz를 권장합니다.** 매끄러움(가속도·최대 속도)이 Unitree 수준이 되고, 저크는 더 낮고, URDF 속도 위반이 사라집니다. 관절은 0.7°, 발은 평균 0.2 cm만 움직입니다. 발바닥 미끄러짐은 0.20%에서 0.45%로 늘지만 Unitree(0.72%)보다 낮습니다.
- 4 Hz와 Savitzky–Golay 11은 빠른 동작(춤·달리기)에서 발이 6–8 cm 밀립니다. 8–10 Hz는 저크가 Unitree보다 큽니다.
- **GMR `--velocity-limit`은 효과가 없습니다.** 출력이 원본과 같습니다. 제한이 IK 반복 한 번의 속도에 걸리고, GMR은 수렴할 때까지 반복을 더 돌기 때문입니다.
- 평활화해도 Unitree와의 일치도(다리 관절 차이 중앙값 4.7°)와 바닥 관통은 그대로입니다.
- 평활화 뒤 IK 위치 잔차를 다시 계산해 json에 전후를 남깁니다. CMU 6클립에서 발 잔차는 0.03–0.23 cm 늘었습니다.
- 발바닥 미끄러짐: 발바닥 접촉구 네 개가 모두 바닥 2.5 cm 이내인 상태에서 0.3 m/s보다 빠르게 0.1 s 이상 움직인 프레임 비율(MuJoCo FK).

### 스윙 발 높이 보정 (`--swing-clearance 2` 권장)

리타겟 결과는 앞으로 내딛는 발이 바닥을 스치기도 합니다. 기구학 재생에서는 티가 안 나지만, 물리에서는 발끝이 걸려 비틀거리거나 넘어집니다(아래 "Isaac 물리 재생"). 원인은 소스마다 달랐습니다.
- CMU 02_01 SMPL-X: 스윙 무릎을 덜 굽혀(최대 65°, BVH 76°) 착지 직전 뒤꿈치가 0.8 cm까지 내려옵니다.
- HF FBX: 발을 떼는 순간 발끝이 71° 아래를 향해 0.6 cm 높이로 끌립니다.

`--swing-clearance CM`(`khumanoid.retarget.ensure_swing_clearance`)은 평활화 뒤에 공통으로 거는 후처리입니다.
- **바닥:** 디딤발(가장 느린 발바닥 점이 0.3 m/s 미만인 발) 중 낮은 쪽의 높이를 클립 내내 따라갑니다(`analysis.floor_track`). 바닥이 떠오르는 클립(02_01은 4–5 cm)에서도 그때그때의 바닥을 씁니다.
- **필요한 높이:** 움직이는 발의 모든 발바닥 점은 그 바닥보다 속도에 비례한 높이 위에 있어야 합니다. 0.3 m/s에서 0, 1 m/s 이상에서 CM입니다. 빠르게 미끄러지는 발이 걸리고, 착지하려고 느려지는 발은 바닥에 가까워도 됩니다.
- **들어 올리는 법:** 모자라면 그 다리의 관절 6개만 가중 최소제곱으로 움직입니다. 너무 낮은 발바닥 점은 올리고, 발의 수평 위치는 유지하고, 발 방향은 약하게만 유지합니다.
- **제약:**
  - 관절당 변화는 20°까지로 제한하고, 못 채운 부족분은 json에 남깁니다. 착지 직전 다리가 펴진 채 바닥 아래로 뻗는 프레임은 다 들려면 무릎을 수십 도 접어야 하기 때문입니다.
  - 디딤발은 건드리지 않고, 루트·몸통·팔도 그대로입니다. 관절 변화는 시간축으로 다듬습니다.

CMU 17클립(BVH 6, FBX 6, SMPL-X 5, `--smooth 6 --swing-clearance 2`, `reports/compare_bvh_fbx_smplx_swing2.md`):
- **스윙 발 바닥 근접:** 크게 줄었습니다.

  | 클립 | BVH | FBX | SMPL-X |
  |---|---|---|---|
  | 02_01 | 17 → 2% | 49 → 3% | 37 → 13% |
  | 143_11 | 27 → 4% | 31 → 5% | 29 → 7% |
  | 143_28 | 15 → 4% | 10 → 0% | 15 → 3% |

- **다리 관절 변화:** RMSE 0.3–2.2°, 순간 최대 3–20°입니다. BVH 대비 다리 관절 차이는 그대로라(02_01 SMPL-X 4.5 → 4.5°) 포맷 비교를 흐리지 않습니다.
- **빠르게 움직이는 발의 최저 높이:** -3.8~+2.0 cm에서 0.8–2.2 cm로 올라갔습니다. 바닥 드리프트는 1–10 cm로, 클립마다 바닥이 꽤 움직입니다.
- **부작용:** 바닥 관통과 발 미끄러짐은 늘지 않았습니다. 발 IK 잔차는 목표보다 발을 띄운 만큼 늘었습니다(예: 02_01 SMPL-X 1.4 → 2.5 cm).
- **물리 효과:** 아래 "Isaac 물리 재생" 표에 있습니다.

검증 결과 (2026-10-15):
- IK 위치 잔차 평균은 발 0.6–1.2 cm, 골반 0.5 cm 미만, 손 7.7–14 cm입니다. 손 잔차는 추종 실패가 아니라 체형 차이입니다. 상완 방향 가중치(100)가 손 위치(10)보다 커서 방향은 1° 안으로 맞고, G1 어깨 위치가 다른 만큼 손 위치가 어긋납니다. GMR 자체 LAFAN1 설정도 손 6–8 cm입니다.
- 같은 LAFAN1 4클립을 GMR과 Unitree 공식 리타겟(csv)으로 비교했습니다. 관절각 차이 중앙값은 7–12°로, 대부분 어깨 yaw·손목 roll 같은 팔 비틀림입니다. 골반 높이 차이는 2.5 cm 미만입니다. Unitree csv의 월드 좌표는 우리 것보다 z축으로 90° 돌아가 있습니다(관례 차이).
- GMR 원본 결과는 Unitree보다 관절 가속도가 30–50% 커서 더 거칩니다(프레임별 IK). `--smooth 6`으로 Unitree 수준이 됩니다(아래).
- 사람과 나란히 재생하면 로봇은 줄어든 보폭으로 걷기 때문에, 클립이 길수록 둘 사이 간격이 벌어집니다.

## 비교 뷰어 (여러 포맷 → 같은 G1)

`tools/compare_viewer.py`는 여러 모션을 같은 G1에 올려 브라우저에서 나란히 재생하고 수치로 비교합니다(viser 기반). 지표 계산은 `khumanoid/analysis.py`에 있습니다.

```powershell
# 같은 촬영의 BVH / FBX / AMASS SMPL-X(몸 메시)와 Isaac 물리 결과를 한 화면에
python tools\compare_viewer.py --body-mesh data\raw\cmu_bvh\143_11.bvh data\raw\cmu_fbx\143_11.fbx data\raw\amass_cmu_smplx\CMU\143\143_11_stageii.npz reports\physics\smooth6\143_11_g1_sim.npz
# 같은 비교를 여러 클립에 대해 표로 (-g 그룹마다 첫 파일이 기준)
python tools\compare_report.py -g data\raw\cmu_bvh\02_01.bvh data\raw\amass_cmu_smplx\CMU\02\02_01_stageii.npz -g ... --out reports\compare.md
# 같은 LAFAN1 클립: 우리 GMR(평활화) vs Unitree 공식 리타겟 vs GMR 원본
python tools\compare_viewer.py data\raw\lafan1_bvh\dance1_subject1.bvh data\raw\unitree_lafan1_g1\dance1_subject1.csv data\retargeted\lafan1\dance1_subject1_g1.npz
# -> 브라우저에서 http://127.0.0.1:8080
```

- **viser는 물리 시뮬레이터가 아닙니다.** 브라우저 3D 뷰어라서 관절각대로 자세를 그릴 뿐이고, 표의 발 미끄러짐·관통도 기하 계산입니다. 물리 정합성은 Isaac(PhysX)에서 계산합니다. 아래 "물리 모드" 버튼을 쓰거나, `isaac_replay.py --physics` 결과 npz를 원래 동작 옆에 놓고 봅니다.
- **물리 모드** ("재생" 탭 맨 위 버튼, 또는 시작할 때 `--physics`):
  - 켜면 각 로봇을 관절각대로 그리지 않고, Isaac Sim PhysX가 시뮬레이션한 결과로 바꿔 그립니다(중력, 마찰 바닥, 관절 토크 한계, 골반 보조 힘). 끄면 원래 기구학 재생으로 돌아옵니다.
  - 결과가 없는 클립은 Isaac을 창 없이 백그라운드로 돌려 만듭니다. 한 번에 한 클립씩 돌고, 짧은 클립은 1분 남짓(대부분 Isaac 시작 시간), 11초 클립은 약 1분 30초입니다. 진행률은 패널과 각 로봇 이름표에 나옵니다.
  - 결과는 모션 내용, `configs/physics.yaml`, 보조 힘 설정으로 키를 만들어 `data/cache/physics/`에 저장합니다. 다음에 켜거나 같은 동작을 다시 열면 바로 나옵니다.
  - "골반 보조 힘"을 끄면(`--assist 0`) 따로 계산합니다. "물리 계산 취소"는 대기 중이거나 도는 중인 Isaac 프로세스를 멈춥니다.
  - 물리 모드에서는 분석 탭의 그래프·표도 시뮬레이션된 동작으로 잽니다("재생 방식" 행). 넘어진 클립은 이름표에 넘어진 시각과 1차 원인이 원인 시작부터 넘어진 뒤 0.5초까지 나옵니다(예: "넘어짐 2.07s · 발끝 걸림 1.47s부터").
  - Isaac Sim의 EULA(NVIDIA Omniverse License Agreement)에 동의해야 돌아갑니다. 동의한 사용자만 `--isaac-accept-eula`로 실행하세요. 없으면 "EULA에 동의하지 않은 상태" 메시지로 실패합니다.
  - Isaac 위치는 환경변수 `KHUMANOID_ISAAC_PYTHON`(설치 폴더의 `python.bat`), 그다음 지금 파이썬(k-humanoid 환경), 그다음 `C:\isaacsim` 순서로 찾습니다(`khumanoid/physics_runner.py`).
- **입력:** 사람 모션(BVH, FBX, AMASS SMPL-X npz)은 리타게팅해서 불러옵니다(기본 `--smooth 6`, 결과는 `data/cache/retarget/`에 캐시). 로봇 모션(npz, Unitree csv, GMR pkl)은 그대로 불러옵니다. Isaac 물리 결과(`*_sim.npz`)는 옆의 json에서 물리 지표를 읽어 함께 보여 줍니다. 실행 중에 "모션" 탭에서 파일을 추가하거나 제거할 수 있습니다.
- **3D:** 모션마다 다른 색의 G1을 나란히 또는 겹쳐서 보여 줍니다. 기본으로 각자의 시작 골반을 원점에, 진행 방향을 +x로 맞춥니다(소스마다 월드 좌표가 달라서). 리타게팅한 모션은 원본 사람을 로봇 크기로 줄여 옆에 그립니다(겹치기, 로봇 반투명 선택 가능). 사람은 기본이 막대 인형이고, SMPL-X 입력은 "사람 표시: 몸 메시"(또는 `--body-mesh`)로 몸 표면을 그립니다. 선형 블렌드 스키닝이며 자세별 보정 블렌드셰이프는 넣지 않았습니다. BVH·FBX에는 몸 표면 정보가 없어서 막대로만 그립니다.
- **재생:** 재생과 일시정지, 시간 슬라이더, ±1 프레임, 속도, 반복을 지원합니다. 모션별 시간 오프셋을 직접 넣거나, 기준 모션에 자동 정렬합니다(다리 관절각 차이가 가장 작은 오프셋).
- **분석:** 관절각·골반 높이·골반 속도 그래프(현재 시점 앞뒤 구간), 모션별 지표 표(관절 가속도·저크·최대 속도, 발바닥 미끄러짐, 바닥 관통, 발 최저점, 스윙 발 바닥 근접, 기준 대비 다리·전체 RMSE, QC, 물리 결과면 보조 힘·넘어짐·토크 한계 초과·판정), 기준 대비 관절별 RMSE 막대그래프를 보여 줍니다.
- **균형 표시**("재생" 탭, 기본 켬)는 바닥에 지지다각형(초록 선), CoM 투영(파랑), ZMP(빨강)를 그립니다. 분석 표에는 "CoM 지지 밖 %", "ZMP 지지 밖 %", "정적 불균형 %"가 나오고, 정적 불균형이 5%를 넘으면 QC가 WARN입니다(GMR MJCF 질량 기준, Isaac 에셋 기준 값과 0.1%p 이내).
- **스윙 발 바닥 근접**은 기구학 지표지만 물리 결과를 잘 예측합니다. 가장 느린 발바닥 점까지 0.5 m/s 넘게 움직이는 발이 그때의 바닥(디딤발 높이를 따라간 값, `analysis.floor_track`) 1 cm 안을 지나는 비율로, 높으면 물리에서 발끝이 걸려 비틀거립니다(아래 "Isaac 물리 재생"). `--swing-clearance 2`(뷰어·비교 리포트에도 같은 옵션)로 보정한 결과를 볼 수 있습니다.
- 로봇 메시는 브라우저로 보내기 전에 4 mm 격자로 단순화합니다(삼각형 38.8만 → 10만, 로봇 3대 로딩이 약 25초에서 5초로 줄어듦). `--mesh-cell 0`이면 원본 그대로 보냅니다.
- 기본으로 이 PC에서만 접속됩니다(`--host 127.0.0.1`). 다른 PC에서 보려면 `--host 0.0.0.0`을 쓰는데, 같은 네트워크의 누구나 열 수 있습니다.

### BVH vs SMPL-X 비교 (같은 촬영, 2026-10-15)

CMU 5클립(02_01, 02_03, 143_11, 143_13, 143_28)을 cgspeed BVH와 AMASS SMPL-X로 각각 G1에 리타게팅해 비교했습니다(`--smooth 6`, 결과 `reports/compare_bvh_vs_smplx.md`, BVH 기준).

| 항목 | SMPL-X (`smplx`, BVH와 같은 유도 설정) | SMPL-X (`smplx-gmr`, GMR 자체 설정) |
|---|---|---|
| 자동 시간 정렬 오프셋 | 0 또는 +1프레임 | 0 또는 +1프레임 |
| BVH 대비 다리 관절 RMSE (중앙값) | 4.5–10.2° | 6.0–10.7° |
| BVH 대비 전체 관절 RMSE | 4.7–9.0° | 6.0–11.3° |
| 바닥 관통 프레임 (BVH 0–6%) | 0–9% | 18–99% (발이 3–5 cm 기울어 바닥을 뚫음) |
| 손 IK 위치 오차 (평균) | 4.9–8.8 cm | 8.2–11.3 cm |

- 두 소스는 프레임까지 같은 촬영입니다. 남는 차이는 주로 어깨·손목 비틀림과, 143번 피험자의 무릎(17–20°)입니다. CMU 원본 골격(ASF)과 AMASS의 SMPL-X 피팅이 같은 동작의 관절각을 다르게 추정한 결과입니다.
- SMPL-X 기준 자세를 맞추는 방식 세 가지를 같은 지표로 비교해 골랐습니다(관절 하나씩 / 팔다리 일괄 + 발 수평 / 발 수평만). 팔다리 일괄 + 발 수평이 SMPL-X 발 IK 오차 1.9 → 1.3 cm, BVH와의 전체 차이 7.9 → 7.4°로 가장 좋았습니다.

### BVH vs FBX 비교 (같은 촬영, 2026-10-16)

CMU 6클립을 두 가지 FBX로 리타게팅해 BVH와 비교했습니다(`reports/compare_bvh_fbx_smplx.md`, SMPL-X 포함).

| FBX | 만든 방법 | BVH 대비 (G1 관절각) |
|---|---|---|
| `data/raw/cmu_fbx_from_bvh` | 우리 cgspeed BVH를 Blender로 FBX 변환(`khumanoid.io.fbx.bvh_to_fbx`) | 관절 위치 왕복 오차 평균 0.01 mm, 리타겟 RMSE 0.0°: FBX 경로가 정확함 |
| `data/raw/cmu_fbx` | Hugging Face `gbionics/cmu-fbx`(RancidMilk가 cgspeed **Daz판** BVH를 Blender·Auto-Rig Pro로 게임 캐릭터 골격에 옮긴 것) | 다리 1.5–4.2°, 전체 3.0–5.0°. 팔꿈치만 17–20° 일정하게 다름(이 골격의 기준 자세에서 팔꿈치가 약간 굽은 것으로 보임) |

- Hugging Face FBX는 원본 cgspeed BVH의 시간 오류를 그대로 물려받았습니다. 60 Hz로 찍은 143번도 120 Hz로 가정해 30 fps로 다시 뽑아서 2배속입니다(143_11: 실제 10.95초가 5.47초로). 로더가 0번 T-pose와 CMU 파일명으로 이를 알아보고, `파일 fps × 실제 촬영 Hz / 120`(143번은 15 fps)으로 고칩니다.
- 이 FBX는 수치가 cm인데 장면 단위는 m라서 100배 큽니다. 로더가 기준 자세 크기로 단위를 자동으로 고칩니다(머리~발 1.41 m, 더 작은 캐릭터로 옮겨져 루트 이동도 그만큼 작음).

## Isaac 물리 재생 (물리 정합성)

비교 뷰어(viser)와 기본 Isaac 재생은 관절각대로 자세를 그리는 **기구학 재생**이라, 바닥을 뚫거나 공중에 떠 있거나 균형이 안 맞는 동작도 그대로 그립니다. `tools/isaac_replay.py --physics`는 Isaac Sim의 PhysX로 로봇을 실제로 시뮬레이션해 "로봇이 이 동작을 자기 발로 할 수 있는가"를 잽니다.

```powershell
python tools\isaac_replay.py --robot-motion data\retargeted\smooth6\02_01_g1.npz --physics --check-out reports\physics\smooth6
python tools\physics_report.py reports\physics --out reports\physics\summary.md
```

- **장면:** 중력 9.81 m/s², 마찰 있는 정적 바닥(정지 1.0, 운동 0.8), 240 Hz(모션 30 fps당 8스텝). 설정은 [configs/physics.yaml](configs/physics.yaml)입니다.
- **구간:** 긴 클립은 `--start 10 --end 30`처럼 일부만 돌립니다(실시간보다 약 5배 느려서 LAFAN1 4분 클립 전체는 20분 넘게 걸림). json의 시각은 구간 시작부터 셉니다(`replayed_s`).
- **로봇:** 첫 프레임 자세에서 출발합니다. 원본 발이 바닥 아래에 있으면 그만큼 올려서 시작합니다.
- **관절 PD:** 관절 드라이브가 리타겟 관절각·각속도를 따라갑니다. 게인은 일부러 높게 잡았습니다(엉덩이·무릎 1500 N·m/rad). 정책 없이 정책 수준 게인(100–200)을 쓰면 디딤 다리가 체중에 10° 넘게 꺾이기 때문입니다. 토크 한계는 에셋 값(엉덩이 88–139, 발목 50 N·m 등)을 그대로 쓰고, 넘는 요구는 "한계 초과"로 셉니다. 요구가 한계의 수 배면 토크가 모자란 것이 아니라 관절이 막힌 것입니다(바닥·물체 접촉).
- **골반 하네스(가상 보조 힘):**
  - 정책이 없으니 균형을 잡는 피드백이 없어서, 골반을 원본의 **수평 위치·자세** 쪽으로 당기는 스프링을 답니다(1 Hz 임계감쇠, 회전 600 N·m/rad).
  - 체중은 발로만 받도록 수직 스프링은 없습니다. 원본이 바닥 위로 뜨거나 바닥으로 파고들면 힘이 아니라 "골반 높이차"로 나옵니다.
  - 이 힘이 클수록 로봇이 자기 발로는 못 하는 동작입니다. `--assist 0`은 하네스 없이 돌립니다. 넘어지면(골반이 50 cm 이상 벗어나거나, 60° 넘게 기울거나, 30 cm 아래로 내려가거나, 원본 골반보다 25 cm 넘게 낮아지면) 그 프레임에서 원본 자세로 다시 시작하고 횟수를 셉니다. 마지막 조건은 무릎을 꿇듯 주저앉은 경우를 잡으려고 나중에 넣었습니다.
- **출력:**
  - `<clip>_sim.npz`: 물리로 실제 움직인 궤적. 뷰어에 원본 옆에 올리면 물리 결과 행이 같이 나옵니다.
  - `<clip>_sim.json`: 하네스 힘, 발 지지력, 추종 오차, 토크, 넘어짐, 물리 상태의 발 지표, 균형(`physics.balance`: 시뮬레이션, 넘어진 뒤 리셋마다 끊어서 ZMP를 계산; `reference_balance`: 원본 클립), 넘어짐 원인(`physics.fall_diagnosis`, 아래).
  - `--video`: 동영상.

**결과** (CMU 3클립 × 리타겟 3종, 2026-10-16, `--smooth 6` → `--smooth 6 --swing-clearance 2`).
- 표: `reports/physics/summary.md`(보정 전), `reports/physics_swing2/summary.md`(보정 후).
- 동영상: `reports/videos/physics/`, `reports/videos/physics_swing2/`.

| 클립 | 리타겟 | 넘어짐 | 보조 힘 평균 (체중 %) | 보조 > 20% 프레임 | 한계 초과 프레임 |
|---|---|---|---|---|---|
| 02_01 걷기 | BVH | 0 → 0 | 10 → 8 | 2 → 0% | 6 → 6% (발목 1.5배) |
| | FBX (HF) | **1** → 0 | 36 → 30 | 85 → 69% | 56 → 27% |
| | SMPL-X | **1** → 0 | 24 → 14 | 63 → 22% | 40 → 17% |
| 143_11 상자 들기 | BVH | 0 → 0 | 20 → 15 | 41 → 25% | 23 → 5% |
| | FBX (HF) | **2** → 0 | 30 → 18 | 61 → 31% | 41 → 9% |
| | SMPL-X | **1** → 0 | 23 → 23 | 50 → 50% | 28 → 29% |
| 143_28 빗자루질 | BVH | 0 → 0 | 43 → 9 | 80 → 5% | 18 → 0% |
| | FBX (HF) | 0 → 0 | 48 → 16 | 83 → 29% | 19 → 1% |
| | SMPL-X | 0 → 0 | 33 → 11 | 58 → 3% | 28 → 0% |

- **보정 전에는 같은 걷기라도 리타겟에 따라 물리적으로 갈렸습니다.** 02_01 BVH 리타겟은 발이 체중의 95%를 받치며 거의 혼자 걸었습니다. SMPL-X·FBX 리타겟은 앞으로 내딛는 발끝이 바닥에 걸려 비틀거리다 넘어졌습니다(`reports/videos/physics/02_01_bvh_physics.mp4` vs `02_01_smplx_physics.mp4`).
  - 원인은 스윙 발 높이였습니다. 뷰어·비교 리포트의 "스윙 발 바닥 근접"(`analysis.foot_metrics`)이 BVH 17%, FBX 49%, SMPL-X 37%로, Isaac 없이도 미리 보였습니다.
- **`--swing-clearance 2`로 넘어짐이 모두 사라졌습니다**(9클립 넘어짐 5회 → 0회). 02_01 SMPL-X는 끝까지 걷습니다. 전후를 나란히 붙인 영상은 `reports/videos/physics_swing2/02_01_smplx_before_after.mp4`입니다.
  - 보조 힘과 "엉덩이 막힘"(요구 토크가 한계의 10–20배)도 대부분 줄었습니다. 상자 들기와 빗자루질에서 엉덩이가 막히던 것도 상당 부분 발끝 걸림 때문이었습니다.
  - 처음에는 빗자루질의 큰 보조 힘을 "사람이 기대는 빗자루가 시뮬레이션에 없어서"라고 봤는데, 틀렸습니다. 발을 끌며 걷는 동작에서 발이 걸린 것이었고, 보정 후에는 BVH 9%, SMPL-X 11%입니다.
- **남은 것:**
  - 02_01 FBX(HF)는 보조 > 20% 프레임이 여전히 69%입니다. 더 작은 캐릭터에서 옮긴 골격이라, 발 높이 말고도 루트와 발 배치가 G1에 덜 맞는 것으로 보입니다.
  - 143_11 SMPL-X는 보조가 그대로(50%)입니다. 바닥까지 숙여 상자를 드는 구간에서 엉덩이가 여전히 막힙니다(8배). 손·팔이 바닥에 닿거나 상자 무게를 다루는 구간이라, 물체를 장면에 넣거나 이 구간을 따로 판정해야 합니다.
  - 착지 직전 다리가 펴진 채 바닥 아래로 뻗는 프레임은 관절 20° 상한 때문에 일부만 들립니다. json의 `remaining_shortfall_cm_max`가 17클립에서 0.7–2.1 cm이고, 143_13(바구니 들기)이 가장 큽니다.
- CMU 02_01 원본은 끝으로 갈수록 발이 바닥 위로 4–5 cm 떠오릅니다(촬영 바닥 기울기 또는 리타게팅 높이 누적). 기구학 QC의 floating(15 cm) 기준으로는 잡히지 않고, 물리 재생에서 골반 높이차로 드러났습니다. 스윙 발 보정은 이 바닥을 따라가며 잽니다.

**넘어짐 원인 진단** (`physics.fall_diagnosis`, `khumanoid/diagnosis.py`, 설정은 `configs/physics.yaml`의 `diagnosis`):
- 보조 힘 없이 넘어졌다는 사실만으로는 데이터 탓인지 알 수 없습니다(균형은 제어기의 몫). 그래서 넘어질 때마다 직전 0.75 s(직전 리셋 이후)를 보고, 원인 후보별로 처음 시작된 시각과 근거 수치를 남깁니다. `--assist 0`에서도 같습니다.
  - **발끝 걸림 (`toe_catch`):** 원본에서는 발이 바닥에서 떠서(0.5 cm 위) 0.5 m/s 넘게 휘두르는 중인데, 시뮬레이션에서는 발이 바닥에 닿음(발바닥 점이 0.5 cm 안 또는 접촉력 > 체중 5%). 근거: 원본 발 속도·높이, 시뮬 발 높이, 접촉력.
  - **발 미끄러짐 (`foot_slip`):** 원본에서는 서 있는 발이 시뮬레이션에서는 바닥에 붙은 채 0.3 m/s 넘게 미끄러짐.
  - **자기충돌 근접 (`self_collision`):** 좌우 발 또는 무릎이 9 cm 안으로 가까워짐. 재생 중에는 자기충돌을 꺼 두므로 대리 지표입니다.
  - **토크 포화 (`torque_saturation`):** 관절 요구 토크가 한계의 1.5배를 넘음. 근거: 관절, 배율, 구간 최대.
  - **지지면 이탈 (`support_exit`):** CoM 투영이 지지다각형 밖 3 cm, 또는 ZMP가 5 cm(보조 힘을 켠 실행에서는 CoM만).
  - **보조 힘 급증 (`harness_spike`):** 하네스가 체중의 50%를 넘게 당김.
- `primary_cause`는 구간 안에서 새로 시작된 조건 중 가장 이른 것입니다. 없으면 이미 계속되던 조건 중 가장 오래된 것이고, 보조 힘 급증은 결과이므로 다른 후보가 없을 때만 고릅니다. 나머지 후보도 시작 시각, 구간 시작 때 이미 켜져 있었는지, 그때부터 계속됐는지와 함께 남깁니다.
- 지지면 이탈의 근거에는 같은 순간 원본 클립의 CoM 여유(`clip_com_margin_cm`)도 남습니다. 원본은 안쪽인데 시뮬레이션만 밖이면 추종 실패이고, 원본도 밖이면 원본 동작 자체가 그렇다는 뜻입니다(걷기의 한 발 지지에서는 정상일 수 있음).
- `physics_report.py` 표의 "넘어짐 원인" 열에 1차 원인과 시각이 나옵니다(넘어짐 3회까지, 나머지는 원인별 횟수).

**진단 예시** (2026-10-16, 하네스 x1 = 기본, x0 = `--assist 0`; `--smooth 6` 리타겟 → `--swing-clearance 2` 보정 후. LAFAN1은 10–30 s 구간. 결과는 scratch에서 돌렸고 `reports/physics*`는 아직 진단 이전 json입니다):

| 클립 | 하네스 | 넘어짐 (s) | 1차 원인 (시작 s) | 근거 | 보정 후 |
|---|---|---|---|---|---|
| CMU 02_01 SMPL-X | x1 | 2.07 | 발끝 걸림 1.47 | 오른발: 원본은 2.8 m/s로 바닥 1.6 cm 위를 지나는데 시뮬 발은 0.1 cm. 뒤이어 엉덩이 토크 2.4배(구간 최대 14.6배), CoM 지지 밖 4.5 cm | 넘어짐 0. 보조 24 → 14%, 한계 초과 40 → 17% |
| CMU 143_11 SMPL-X | x1 | 3.07 | 발끝 걸림 2.40 | 왼발: 원본 3.3 m/s·4.0 cm 위, 시뮬 −0.1 cm, 접촉력 722 N. 뒤에 하네스 급증, 발 미끄러짐, 발 사이 5.6 cm | 넘어짐 0 |
| CMU 143_11 FBX | x1 | 2.77 | 지지면 이탈 2.20 | 한 발 지지에서 CoM 4.2 cm 밖(원본은 2.7 cm 안). 0.1 s 뒤 발끝 걸림(왼발 3.2 m/s), 엉덩이 3.7배 | 넘어짐 0. 보조 30 → 18%, 한계 초과 41 → 9% |
| | | 9.97 | 지지면 이탈 (6.77부터 계속) | 상자를 들며 숙인 구간에서 시뮬 CoM이 40 cm 밖(원본은 3.7 cm 안), 엉덩이 7.6배 | 〃 |
| LAFAN1 walk1 | x1 | 없음 | - | | 넘어짐 0. 보조 25 → 14%, 한계 초과 29 → 5% |
| LAFAN1 run1 | x1 | 없음 | - | | 그대로(보조 16%, 한계 초과 26%) |
| CMU 02_01 BVH | x0 | 1.07, 2.37 | 지지면 이탈 0.37, 토크 포화 2.07 | 두 발 다 바닥인데 ZMP 11 cm 밖 / 왼 엉덩이 2.3배 | 1.07, 2.50 그대로 |
| CMU 02_01 SMPL-X | x0 | 0.93, 2.27 | 지지면 이탈 0.37, 1.63 | ZMP 8 cm 밖 / CoM 4.8 cm 밖 | 1.07, 1.87 (발끝 걸림 0.40, 발 미끄러짐 1.27) |
| LAFAN1 walk1 | x0 | 16회 | 지지면 이탈 8, 발끝 걸림 5, 미끄러짐 2, 토크 1 | 첫 넘어짐: 1.53 s, CoM 3.1 cm 밖(원본은 5.9 cm 안) | 13회 (지지면 이탈 5, 토크 4, 발끝 걸림 3, 미끄러짐 1) |

- **하네스를 켠 실행에서는 진단과 보정 결과가 맞습니다.** 발끝 걸림으로 진단된 넘어짐(SMPL-X 02_01, 143_11)은 스윙 발 보정으로 모두 사라졌습니다.
- **FBX 143_11의 첫 넘어짐은 한계를 보여 줍니다.** 지지면 이탈이 발끝 걸림보다 0.1 s 먼저 잡혔지만, 보정 후 넘어짐이 사라졌으니 실제 원인은 발끝 걸림 쪽이었을 가능성이 큽니다. 같은 비틀거림 안에서 0.1 s 차이로 켜진 후보들은 "가장 이른 것" 규칙만으로 가르기 어렵습니다. 후보 목록 전체를 같이 봐야 합니다.
- **보조 힘 없이(x0) 걸으면 보정과 상관없이 1–2초마다 넘어집니다.** 첫 원인은 대개 지지면 이탈이고, 그때 원본 CoM은 지지면 안쪽입니다. 데이터가 아니라 균형 제어기가 없어서 넘어진다는 뜻입니다. 그래서 데이터 판정은 하네스 실행의 넘어짐·보조 힘·원인으로 하고, x0 결과는 참고로만 씁니다.
- 발끝 걸림 근거의 접촉력 0 N은 발이 바닥 0.5 cm 안까지 내려왔지만 아직 힘이 잡히지 않은 스침입니다.
- 판정 기준(하네스 > 체중 20% 프레임 5% 이하, 한계 초과 프레임 5% 이하, 넘어짐 0)은 `configs/physics.yaml`의 `report`에서 바꿉니다.
  - 보정 후 143_28 BVH·SMPL-X가 처음으로 통과했습니다.
  - 02_01 BVH(발목 토크 5.8%)와 143_11 BVH는 아깝게 걸립니다.

## 공개 샘플 데이터와 라이선스

`python tools\fetch_samples.py`로 받습니다. 리비전을 고정하고 파일별 해시를 확인하며, 폴더마다 `SOURCE.md`에 출처·리비전·라이선스·해시를 남깁니다.

| 폴더 | 내용 | 라이선스 | 사용 범위 |
|---|---|---|---|
| `data/raw/cmu_bvh` | CMU mocap(cgspeed 2010 BVH 변환본) 6클립, 총 40 s: 02_01 걷기, 02_03 조깅, 16_17 걷다 좌회전(이상 120 Hz), 143_11 상자 들기, 143_13 빨래바구니 들기, 143_28 빗자루질(이상 60 Hz) | CMU 약관(상업 사용·재배포 허용, 데이터 판매 금지) | **공개 데이터셋 사용 가능**. 사사 문구는 SOURCE.md |
| `data/raw/amass_cmu_smplx` | AMASS CMU SMPL-X N 전체(2,080 파일, 8.6 GB, 사용자가 직접 받음). 비교에는 위 BVH와 같은 5클립을 씀(16_17은 AMASS에 없음) | AMASS 비상업 연구 라이선스 | **내부 검증 전용** |
| `data/raw/cmu_fbx` | 위 6클립의 FBX(Hugging Face `gbionics/cmu-fbx`, 0.8 MB, sha256 확인) | CMU 약관 | **공개 데이터셋 사용 가능** |
| `data/raw/cmu_fbx_from_bvh` | 위 6클립 BVH를 Blender로 변환한 FBX(우리가 만든 파생물, 테스트용) | CMU 약관 | 공개 가능 |
| `data/raw/unitree_lafan1_g1` | Unitree의 LAFAN1→G1 리타겟 csv 4클립(30 fps, 13.3분) | CC BY-NC-ND 4.0 | **내부 검증 전용**. 재배포·파생물 공유 금지 |
| `data/raw/lafan1_bvh` | 같은 4클립의 LAFAN1 원본 BVH(137 MB zip에서 4개만 남김) | CC BY-NC-ND 4.0 | **내부 검증 전용** |

리타게팅 결과는 원본 라이선스를 따릅니다. `data/retargeted/lafan1/`은 LAFAN1의 파생물이므로 내부용입니다.

## 지원 포맷

| 확장자 | 내용 | 로더 |
|---|---|---|
| `.bvh` | 스켈레톤 회전 애니메이션 (Vicon/OptiTrack/Xsens/Rokoko 내보내기, CMU, LAFAN1). 단위(cm/inch/m)는 키로 자동 추정. CMU cgspeed 변환본의 0번 T-pose 프레임은 자동으로 뺌 | `khumanoid/io/bvh.py` |
| `.fbx` | 스켈레톤 애니메이션 (MotionBuilder, Vicon Shogun, OptiTrack Motive, Xsens MVN, Mixamo, Blender). Blender 임포터로 읽음(Blender 4.5 필요). 단위가 어긋난 파일(cm 수치를 m로 저장)은 기준 자세 크기로 자동 보정. 테이크가 여럿이면 `take=` | `khumanoid/io/fbx.py` |
| `.c3d` | 광학 마커 궤적 (원시 데이터, 결측은 NaN) | `khumanoid/io/c3d.py` (ezc3d) |
| `.npz` (AMASS) | SMPL / SMPL+H / SMPL-X 파라미터. 관절 계산에 바디모델 파일 필요 (`--smpl-model-dir` 또는 `SMPL_MODEL_DIR`) | `khumanoid/io/smpl.py` |
| `.npz` (로봇) | 프로젝트 표준 로봇 모션: `fps, joint_names, root_pos, root_quat_wxyz, dof_pos` (`tools/retarget.py` 출력) | `khumanoid/io/robot.py` |
| `.csv` | Unitree 리타게팅 csv (`x y z qx qy qz qw q1..qn`, 헤더 없음, 30 fps) | `khumanoid/io/robot.py` |
| `.pkl` | GMR(General Motion Retargeting) 출력 (직접 만든 파일만 열 것: pickle) | `khumanoid/io/robot.py` |

모든 로더는 Isaac Sim 좌표계(**Z-up, m, 쿼터니언 wxyz**)로 변환해서 돌려줍니다.
xyzw를 쓰는 포맷(Unitree csv, GMR)은 로더에서 변환합니다. 쿼터니언 순서는 포맷마다 다르니 [조사 자료 1.4절](docs/research/mocap_survey.md)을 참고하세요.

## 검증(QC) 기준

임계값은 [configs/qc.yaml](configs/qc.yaml)에서 조정합니다. 공개 스튜디오 데이터로 한 번 점검했고(아래), 자체 촬영 데이터가 들어오면 다시 확인해야 합니다.
프레임에 *hard* 플래그가 붙으면 그 프레임은 유효시간에서 빠집니다.

| 플래그 | 대상 | 의미 |
|---|---|---|
| `nan` / `missing_markers` | 사람, 로봇 | 결측(NaN), 또는 마커 가림 비율 초과 |
| `spike` | 사람 | 관절 속도 > 15 m/s (마커 스왑·솔버 튐). 1초 안에 튀었다 돌아오면 그 사이 구간 전체 |
| `penetration` / `floating` | 사람 | 발이 바닥 3 cm 아래 / 몸 전체(가장 낮은 관절)가 0.5 s 이상 15 cm 위 |
| `skating` (soft) | 사람 | 발 관절이 자기 바닥 높이 2 cm 안에서 0.3 m/s보다 빠르게 0.1 s 이상 미끄러짐 |
| `joint_limit` / `joint_velocity` | 로봇 | URDF 또는 로봇 에셋의 관절 한계(0.01 rad 허용)·속도 위반 |
| `fallen` | 로봇 | 루트 기울기 > 75° 또는 높이 < 0.25 m |
| `static_unbalanced` (soft) | 로봇 (로봇 모델 필요: Isaac 검사, 뷰어, `qc_report.py --balance`) | 거의 멈춘 채(CoM < 0.1 m/s) CoM 투영이 발 지지다각형 밖 2 cm 넘게 0.2 s 이상. 5% 넘으면 클립 WARN |

- **클립 판정**: hard 프레임 ≤ 2% → PASS, ≤ 10% → WARN, 그 이상 → FAIL(유효시간 0).
- **균형을 soft로 둔 이유** (2026-10-16 조사, 리타겟 44개):
  - `static_unbalanced`는 근사가 들어가지 않는 정적 조건입니다. 몸이 거의 멈춰 있는데 질량중심이 발 밖에 있으면, 로봇이든 사람이든 넘어지거나 화면에 없는 무언가에 기대고 있다는 뜻입니다.
  - 깨끗한 CMU·LAFAN1 리타겟과 Unitree 공식 리타겟은 0–1%였고, LAFAN1 넘어졌다 일어나기는 12%였습니다(손으로 바닥 짚기는 다각형에 없음).
  - CMU 143번 피험자 리타겟(BVH·FBX·SMPL-X 모두)은 22–39%였습니다. 리타겟된 발이 디딤 중에 발끝이 4–16° 들려(정상은 −1~−4°) 뒤꿈치로만 서 있기 때문입니다.
  - 유효시간까지 깎는 hard 플래그로 하지 않은 이유는 두 가지입니다. 다각형이 발만 알아서 손이나 물체로 지지하는 동작도 걸리고, 균형을 실제로 잡는 것은 제어기(WBC/MPC, 추적 정책)의 몫이기 때문입니다.
- **ZMP 이탈은 플래그로 쓰지 않고 지표로만 냅니다.** cart-table 근사로는 Unitree 공식 리타겟의 LAFAN1 춤·달리기도 58–67% 프레임이 지지면 밖으로 나옵니다(각운동량 무시, 공중 구간). 좋은 데이터와 나쁜 데이터를 가르지 못합니다.
- **유효시간**: `hard 플래그 없는 프레임 수 / fps`를 사람 모션에 대해 합산합니다. 목표(5 h) 대비 진척률로 보고합니다.

### 실데이터 점검 (2026-10-15)

대상은 사람 10클립(CMU 6, LAFAN1 4)과 로봇 20클립(Unitree csv 4, GMR 리타겟 10, 그중 CMU 6클립의 `--smooth 6` 결과 6)입니다. 결과는 `reports/qc_real.md`, `reports/sim_check/`, `reports/sim_check_smooth6/`에 있습니다.

바꾼 것:
- **skating**: 접지 기준을 5 cm에서 2 cm로 낮추고 0.1 s 지속 조건을 넣었습니다. 전에는 깨끗한 클립도 25–72%가 skating으로 잡혀 10클립이 모두 WARN이었습니다. 뒤꿈치 착지·발끝 떼기 순간을 잡은 것입니다. 바꾼 뒤 일반 걷기·뛰기·춤은 0–5%, 제자리 회전(16_17) 13%, 빗자루질 발 끌기(143_28) 20%(WARN), 일부러 미끄러지게 만든 합성 걷기는 65%입니다.
- **floating**: 발 대신 몸 전체의 가장 낮은 관절로 판단합니다. 넘어졌다 일어나기 클립에서 누워서 발을 든 구간이 "떠 있음"(1.7%)으로 잡혔습니다.
- **joint_limit_margin** 0 → 0.01 rad: IK 해가 관절 한계에 붙어 있을 때 1e-4 rad 미만의 반올림 오차로 걸렸습니다.
- **CMU 0번 프레임**: cgspeed 변환본은 0번 프레임이 변환기가 넣은 T-pose입니다. 그대로 두면 T-pose에서 첫 프레임으로 넘어가는 점프가 100 m/s spike로 잡혀서, 로더가 자동으로 뺍니다(`load_bvh(drop_tpose=...)`).
- **CMU 60 Hz 피험자**: cgspeed 변환본은 모든 파일에 120 fps를 적었지만, 20명(143번 등, 495개 시도)은 60 Hz로 촬영됐습니다. 그대로 쓰면 2배속이 됩니다(143_11: 실제 10.95초가 5.47초로). AMASS가 보존한 C3D 헤더 값으로 시도별 표(`khumanoid/io/cmu_frame_rates.json`, `tools/cmu_frame_rates.py`로 생성)를 만들었습니다. BVH 로더가 cgspeed 파일이면 이 표로 fps를 고치고, `meta["fps_note"]`에 이유를 남깁니다. 이 수정 전에 만든 143번 리타겟·영상·유효시간은 2배 빨랐습니다(모두 다시 만듦).
- `isaac_replay.py`가 `configs/qc.yaml`을 읽지 않고 코드 기본값만 쓰던 것을 고쳤습니다.

그대로 둔 것: spike 15 m/s(깨끗한 데이터 최대 6–12 m/s로 여유 충분), penetration 3 cm(걸린 프레임 0–0.3%), 클립 판정 비율.

Isaac Sim 헤드리스 검사(CMU 143_11, 16_17, 02_01을 G1과 나란히 재생):
- 사람·로봇 QC 모두 PASS이고 QC 플래그 프레임은 0입니다. 로봇 관절한계는 에셋에서 읽은 값입니다.
- 발바닥 최저점은 -2.1~-2.8 cm, -2 cm 아래 프레임은 0.6–3.5%입니다. 당시에는 보이는 메시 박스로 재서 1.7 cm 낮게 나왔습니다(지금은 충돌체 기준, 아래 "알려진 한계"). 양발 공중 0%, 발바닥 미끄러짐 0%, 붙어 있는 발의 평균 수평속도 0.07–0.11 m/s입니다.
- `--smooth 6` 결과(`reports/sim_check_smooth6/`)도 모두 PASS입니다. 최대 관절속도가 줄고(143_11 18.8 → 15.1 rad/s), 발 지표는 거의 같습니다(-2 cm 아래 143_11 0.6% → 0%, 나머지 동일, 미끄러짐 0%).
- 처음 이 표에 적었던 "발 미끄러짐 0%"는 잘못 센 값이었습니다. 30 fps 로봇을 120 fps 시계로 세어 같은 자세가 반복됐고, 그래서 0.1 s 지속 조건이 성립할 수 없었습니다. 지금은 로봇 프레임 기준으로 셉니다.

결정이 필요한 것: `fallen`은 hard 플래그라서 넘어졌다 일어나기 클립을 FAIL로 만듭니다(Unitree·GMR 모두 31–34% 프레임). 데이터 오류가 아니라 동작 내용입니다. 태스크에 낙상·바닥 동작이 들어가면 soft로 바꾸거나 태스크별로 끄는 것이 맞습니다.

## 폴더 구조

```
khumanoid/          모션 로더, 공통 데이터 구조, QC (numpy만 사용 → Isaac Sim Python에서도 동작)
  retarget.py       GMR 연동 (GMR·mujoco는 함수 안에서만 import)
  analysis.py       모션 비교 지표 (시간 정렬, 관절 RMSE, 매끄러움, 발바닥·균형 지표, 바닥 추적)
  stability.py      균형: 전신 CoM, cart-table ZMP, 발 지지다각형, 부호 있는 여유, 정적 불균형
  diagnosis.py      물리 재생에서 넘어짐의 첫 원인 진단
  physics_runner.py Isaac 물리 실행을 백그라운드 프로세스로 돌리고 결과 캐시 (뷰어 물리 모드, 캐시: data/cache/physics/)
  compare.py        여러 포맷을 같은 로봇으로 불러오기 (리타게팅 캐시: data/cache/retarget/)
  io/cmu_frame_rates.json  CMU 시도별 실제 촬영 fps (cgspeed BVH 보정용)
  io/fbx.py, io/blender_fbx_script.py  FBX 읽기(헤드리스 Blender, 캐시: data/cache/fbx/), BVH -> FBX 변환
  io/smpl.py        AMASS SMPL/SMPL-X (관절 FK, BodyMeshRig: 몸 메시 스키닝)
tools/              retarget.py, compare_viewer.py, compare_report.py, qc_report.py, isaac_replay.py (--physics),
                    physics_report.py, fetch_samples.py, make_samples.py, cmu_frame_rates.py
configs/qc.yaml     QC 임계값, 목표 시간
configs/physics.yaml  Isaac 물리 재생: PD 게인, 골반 보조 힘, 넘어짐·판정 기준
requirements.md     환경 재현 요구사항 (버전, 드라이버, 네트워크), environment.lock.txt: conda 잠금 파일
scripts/            install_isaacsim.ps1, setup_env.ps1, install_gmr.ps1
docs/research/      사전 조사 자료
tests/              pytest (python -m pytest tests; GMR이 없으면 리타게팅 E2E 테스트만 skip)
data/  reports/     (git 제외) data/raw 공개 샘플, data/retargeted 로봇 npz, QC·시뮬 검사 결과
```

## 배포 형태 메모 (실행파일)

최종 결과물은 내려받아 실행하는 프로그램입니다. 아직 패키징은 하지 않았지만, 아래 원칙으로 만들고 있습니다.

- **화면은 비교 뷰어가 바탕입니다.** 로컬 웹 서버 + 브라우저 UI(viser)라서 PyInstaller 같은 도구로 묶을 수 있습니다.
- **Isaac Sim은 묶지 않고 따로 설치한 것을 호출합니다.** 수십 GB이고, NVIDIA RTX GPU와 자체 EULA가 필요하기 때문입니다. 물리 계산은 별도 프로세스로 돌고(`khumanoid/physics_runner.py`), 그 위치는 설정으로 바꿀 수 있습니다. 묶인 실행파일 안에서는 자기 자신(`sys.executable`)을 Isaac 파이썬으로 쓰지 않습니다.
- **EULA 동의는 사용자가 직접 합니다.** 지금은 `--isaac-accept-eula` 옵션이고, 프로그램에서는 설정 화면의 동의 절차로 바꿀 자리입니다.
- **남은 일:**
  - 경로가 아직 저장소 기준입니다(`data/cache/`, `configs/`, `..\GMR`). 실행파일에서는 사용자 데이터 폴더와 프로그램 폴더로 나눠야 합니다.
  - GMR(코드·G1 에셋), mujoco, Blender(FBX)의 포함 여부와 라이선스를 정해야 합니다.
  - 물리 계산을 Isaac 없이도 돌릴 수 있게 MuJoCo 물리를 대안으로 둘지 정해야 합니다.

## 알려진 한계와 다음 단계

- SMPL-X 몸 메시는 비교 뷰어(viser)에만 있습니다. Isaac 재생에서는 사람을 스틱 피겨로만 그립니다(메시는 UsdSkel 필요).
- FBX는 Blender가 있어야 읽힙니다. 기준 자세는 아마추어의 rest pose를 T-pose로 가정합니다. A-pose로 바인딩된 리그(일부 Xsens·게임 리그)는 `--ref <T-pose 프레임>`을 주어야 합니다. 자체 촬영 장비의 FBX로는 아직 확인하지 않았습니다.
- 로봇 발바닥 높이는 발 링크 **충돌체**의 바운딩박스로 근사합니다(2026-10-16부터). 그 전에는 보이는 메시의 박스를 써서 약 1.7 cm 낮게 나왔습니다. `reports/sim_check*`의 발 최저점(-2.1~-2.8 cm)은 그때 값입니다.
- SMPL-X 경로는 AMASS SMPL-X N(중립 모델)으로만 확인했습니다. 성별 모델 파일(SMPL-X G)과 SMPL+H 파일은 리타게팅을 해 보지 않았습니다.
- GMR 결과는 바닥을 제약하지 않습니다. LAFAN1 춤·넘어졌다 일어나기에서 발이 바닥 아래 7–9 cm까지 내려가고 -2 cm 아래 프레임이 0.7–7.9%입니다(Unitree 0.03–1.6%). 평활화로는 바뀌지 않으므로, 바닥 동작을 쓰려면 IK에 바닥 제약을 넣거나 발 높이를 뒤처리해야 합니다.
- CMU 143번 피험자의 리타겟(BVH·FBX·SMPL-X 모두)은 디딤발이 발끝 4–16° 들린 채라 뒤꿈치로만 섭니다(정상 −1~−4°, 02_01 SMPL-X도 +5°). 균형 지표의 정적 불균형 22–39%가 이것입니다. 원인은 발 방향 오프셋(T-pose 기준 자세의 발과 실제 디딤 자세의 발이 다름)으로 보이며, 디딤 구간의 발을 평평하게 맞추는 보정이 필요합니다.
- T-pose 설정의 로봇 자세 맞춤과 관절 중심 보정은 G1에만 정의되어 있습니다(`khumanoid/retarget.py`의 `TPOSE_CHAINS`, `JOINT_CENTERS`). LG 휴머노이드가 오면 MJCF를 GMR `params.py`에 등록하고, LAFAN1 형식 IK 설정과 이 두 표를 추가합니다.
- 손가락과 물체 접촉은 리타게팅하지 않습니다.
- 물리 재생은 정책 없는 PD 추종 + 골반 보조 힘이라, "로봇이 이 동작을 할 수 있는가"의 근사입니다. 최종 판정은 트래킹 정책(GMT·BeyondMimic 계열)을 학습해 보조 힘 없이 따라가는지로 해야 합니다.
- 공개 5 h 데이터는 라이선스 제약으로 자체 촬영분(공개 동의서 확보)으로 채우는 것이 안전합니다(조사 자료 2.4절). 공개 샘플 중에서는 CMU만 공개 가능합니다.
