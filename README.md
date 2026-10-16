# K-Humanoid — Human MoCap 데이터셋 도구

K-온디바이스 휴머노이드 과제의 1차년도 산출물인 **Human MoCap 기반 전신 모션 데이터셋**을 모으고 검증하기 위한 작업 폴더입니다.
아직 Task–Subtask 정의 전이라, 지금 있는 것은 아래 네 가지입니다.

1. **사전 조사**: 모캡 데이터 포맷, 공개 데이터셋(라이선스 포함), 배우용 레퍼런스 영상, 리타게팅 툴 → [docs/research/mocap_survey.md](docs/research/mocap_survey.md)
2. **QC와 유효시간 집계**: 모캡 파일을 프레임 단위로 검사해 "유효 데이터 시간"을 합산합니다(목표 5 h). → `tools/qc_report.py`
3. **리타게팅**: 사람 모캡(BVH, AMASS SMPL-X)을 GMR로 Unitree G1(29 DoF)에 옮겨 프로젝트 표준 로봇 npz로 저장합니다. → `tools/retarget.py`
4. **Isaac Sim 시각화 재현**: 사람 모캡(스틱 피겨)과 리타게팅된 로봇 모션을 Isaac Sim에서 나란히 재생하며 검증합니다. → `tools/isaac_replay.py`

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

## 사용법

```powershell
conda activate k-humanoid

# 동작 확인용 합성 샘플 생성 (data/samples/): 사람 BVH(정상/글리치), G1 로봇 npz/csv
python tools\make_samples.py

# 공개 샘플 받기 (data/raw/, 출처·라이선스는 각 폴더의 SOURCE.md)
python tools\fetch_samples.py                  # cmu, unitree, lafan1 전부 (약 150 MB 다운로드, 남는 건 약 30 MB)
python tools\fetch_samples.py cmu              # CMU BVH 6개만 (2.3 MB)

# 1) 리타게팅: 사람 BVH / AMASS SMPL-X -> G1 npz (data/retargeted/<clip>_g1.npz + .json)
python tools\retarget.py data\raw\cmu_bvh --smooth 6        # 6 Hz 평활화 권장 (기본값은 끔)
python tools\retarget.py data\raw\lafan1_bvh --out-dir data\retargeted\lafan1
python tools\retarget.py clip_stageii.npz --smpl-model-dir models   # SMPL-X 바디모델 필요

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
- 매 프레임 루트 자세와 관절각을 텔레포트하는 kinematic replay입니다. 중력은 끄고, 바닥은 충돌 없는 시각용입니다. 관통을 해소하지 않고 그대로 보여주기 위해서입니다.
- 기본 로봇은 Isaac Sim 에셋 서버의 **Unitree G1(29 DoF + 손)**입니다. LG 휴머노이드 에셋이 오기 전까지 대용으로 쓰며, 이후 `--robot-usd`로 교체합니다.
- 관절은 이름으로 매칭합니다. 모션에 없는 로봇 관절(예: 손가락)은 0으로 둡니다.

**헤드리스 검사 결과** (`<clip>_sim_check.json`, PNG)
- 사람 QC와 로봇 QC 결과가 들어갑니다. 로봇 QC의 관절한계는 로봇 에셋에서 직접 읽습니다.
- 시뮬레이터에서 측정한 발바닥 높이로 관통 비율, 양발 공중 비율, 발 미끄러짐 비율을 계산합니다.
- 스냅샷은 클립 전체에서 고르게 뽑은 프레임과, QC에 걸린 구간의 중간 프레임입니다.
- QC 임계값은 `configs/qc.yaml`을 읽습니다(`--qc-config`).
- 로봇 발 지표는 로봇 프레임마다 한 번씩 셉니다. 재생 시계는 더 빠른 클립(사람 120 fps)을 따르므로, 30 fps 로봇 자세가 4번씩 반복되기 때문입니다.
- 발 미끄러짐은 발바닥 전체가 바닥에 붙은 상태(발 박스 아랫면 네 꼭짓점이 모두 2.5 cm 이내)에서 0.3 m/s보다 빠르게 0.1 s 이상 미끄러진 비율입니다. 최저점만 보면 스윙 중 발끝 스침까지 접지로 셉니다(CMU 리타겟에서 39% vs 0.8%).

## 리타게팅 (사람 → G1)

`tools/retarget.py`(본체는 `khumanoid/retarget.py`)가 GMR의 프레임별 differential IK(mink + MuJoCo)로 G1 29 DoF 관절각을 풉니다. CPU에서 초당 170~230 프레임입니다.

| 입력 (`--format auto`가 고름) | 처리 |
|---|---|
| `tpose`: T-pose 기준 BVH (CMU cgspeed 변환본, Vicon/OptiTrack/Xsens/Rokoko 내보내기) | GMR에 이 스켈레톤용 설정이 없어 클립마다 만듭니다(아래). CMU는 변환기가 넣은 0번 T-pose 프레임을 기준으로 쓰고 출력에서는 뺍니다. 그 밖의 파일은 rest pose가 기준입니다(`--ref <frame>`으로 변경) |
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

검증 결과 (2026-10-15):
- IK 위치 잔차 평균은 발 0.6–1.2 cm, 골반 0.5 cm 미만, 손 7.7–14 cm입니다. 손 잔차는 추종 실패가 아니라 체형 차이입니다. 상완 방향 가중치(100)가 손 위치(10)보다 커서 방향은 1° 안으로 맞고, G1 어깨 위치가 다른 만큼 손 위치가 어긋납니다. GMR 자체 LAFAN1 설정도 손 6–8 cm입니다.
- 같은 LAFAN1 4클립을 GMR과 Unitree 공식 리타겟(csv)으로 비교했습니다. 관절각 차이 중앙값은 7–12°로, 대부분 어깨 yaw·손목 roll 같은 팔 비틀림입니다. 골반 높이 차이는 2.5 cm 미만입니다. Unitree csv의 월드 좌표는 우리 것보다 z축으로 90° 돌아가 있습니다(관례 차이).
- GMR 원본 결과는 Unitree보다 관절 가속도가 30–50% 커서 더 거칩니다(프레임별 IK). `--smooth 6`으로 Unitree 수준이 됩니다(아래).
- 사람과 나란히 재생하면 로봇은 줄어든 보폭으로 걷기 때문에, 클립이 길수록 둘 사이 간격이 벌어집니다.

## 비교 뷰어 (여러 포맷 → 같은 G1)

`tools/compare_viewer.py`는 여러 모션을 같은 G1에 올려 브라우저에서 나란히 재생하고 수치로 비교합니다(viser 기반). 지표 계산은 `khumanoid/analysis.py`에 있습니다.

```powershell
# BVH와 같은 촬영의 AMASS SMPL-X를 각각 리타게팅해 비교 (SMPL-X 바디모델 필요)
python tools\compare_viewer.py data\raw\cmu_bvh\143_11.bvh data\raw\amass_cmu_smplx\CMU\143\143_11_stageii.npz
# 같은 비교를 여러 클립에 대해 표로 (-g 그룹마다 첫 파일이 기준)
python tools\compare_report.py -g data\raw\cmu_bvh\02_01.bvh data\raw\amass_cmu_smplx\CMU\02\02_01_stageii.npz -g ... --out reports\compare.md
# 같은 LAFAN1 클립: 우리 GMR(평활화) vs Unitree 공식 리타겟 vs GMR 원본
python tools\compare_viewer.py data\raw\lafan1_bvh\dance1_subject1.bvh data\raw\unitree_lafan1_g1\dance1_subject1.csv data\retargeted\lafan1\dance1_subject1_g1.npz
# -> 브라우저에서 http://127.0.0.1:8080
```

- **입력:** 사람 모션(BVH, AMASS SMPL-X npz)은 리타게팅해서 불러옵니다(기본 `--smooth 6`, 결과는 `data/cache/retarget/`에 캐시). 로봇 모션(npz, Unitree csv, GMR pkl)은 그대로 불러옵니다. 실행 중에 "모션" 탭에서 파일을 추가하거나 제거할 수 있습니다.
- **3D:** 모션마다 다른 색의 G1을 나란히 또는 겹쳐서 보여 줍니다. 기본으로 각자의 시작 골반을 원점에, 진행 방향을 +x로 맞춥니다(소스마다 월드 좌표가 달라서). 리타게팅한 모션은 원본 사람 스켈레톤을 로봇 크기로 줄여 옆에 그립니다(겹치기, 로봇 반투명 선택 가능).
- **재생:** 재생과 일시정지, 시간 슬라이더, ±1 프레임, 속도, 반복을 지원합니다. 모션별 시간 오프셋을 직접 넣거나, 기준 모션에 자동 정렬합니다(다리 관절각 차이가 가장 작은 오프셋).
- **분석:** 관절각·골반 높이·골반 속도 그래프(현재 시점 앞뒤 구간), 모션별 지표 표(관절 가속도·저크·최대 속도, 발바닥 미끄러짐, 바닥 관통, 발 최저점, 기준 대비 다리·전체 RMSE, QC), 기준 대비 관절별 RMSE 막대그래프를 보여 줍니다.
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

## 공개 샘플 데이터와 라이선스

`python tools\fetch_samples.py`로 받습니다. 리비전을 고정하고 파일별 해시를 확인하며, 폴더마다 `SOURCE.md`에 출처·리비전·라이선스·해시를 남깁니다.

| 폴더 | 내용 | 라이선스 | 사용 범위 |
|---|---|---|---|
| `data/raw/cmu_bvh` | CMU mocap(cgspeed 2010 BVH 변환본) 6클립, 총 40 s: 02_01 걷기, 02_03 조깅, 16_17 걷다 좌회전(이상 120 Hz), 143_11 상자 들기, 143_13 빨래바구니 들기, 143_28 빗자루질(이상 60 Hz) | CMU 약관(상업 사용·재배포 허용, 데이터 판매 금지) | **공개 데이터셋 사용 가능**. 사사 문구는 SOURCE.md |
| `data/raw/amass_cmu_smplx` | AMASS CMU SMPL-X N 전체(2,080 파일, 8.6 GB, 사용자가 직접 받음). 비교에는 위 BVH와 같은 5클립을 씀(16_17은 AMASS에 없음) | AMASS 비상업 연구 라이선스 | **내부 검증 전용** |
| `data/raw/unitree_lafan1_g1` | Unitree의 LAFAN1→G1 리타겟 csv 4클립(30 fps, 13.3분) | CC BY-NC-ND 4.0 | **내부 검증 전용**. 재배포·파생물 공유 금지 |
| `data/raw/lafan1_bvh` | 같은 4클립의 LAFAN1 원본 BVH(137 MB zip에서 4개만 남김) | CC BY-NC-ND 4.0 | **내부 검증 전용** |

리타게팅 결과는 원본 라이선스를 따릅니다. `data/retargeted/lafan1/`은 LAFAN1의 파생물이므로 내부용입니다.

## 지원 포맷

| 확장자 | 내용 | 로더 |
|---|---|---|
| `.bvh` | 스켈레톤 회전 애니메이션 (Vicon/OptiTrack/Xsens/Rokoko 내보내기, CMU, LAFAN1). 단위(cm/inch/m)는 키로 자동 추정. CMU cgspeed 변환본의 0번 T-pose 프레임은 자동으로 뺌 | `khumanoid/io/bvh.py` |
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

- **클립 판정**: hard 프레임 ≤ 2% → PASS, ≤ 10% → WARN, 그 이상 → FAIL(유효시간 0).
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
- 발바닥 최저점은 -2.1~-2.8 cm, -2 cm 아래 프레임은 0.6–3.5%입니다(아래 "알려진 한계"의 발 박스 차이 1.7 cm 포함). 양발 공중 0%, 발바닥 미끄러짐 0%, 붙어 있는 발의 평균 수평속도 0.07–0.11 m/s입니다.
- `--smooth 6` 결과(`reports/sim_check_smooth6/`)도 모두 PASS입니다. 최대 관절속도가 줄고(143_11 18.8 → 15.1 rad/s), 발 지표는 거의 같습니다(-2 cm 아래 143_11 0.6% → 0%, 나머지 동일, 미끄러짐 0%).
- 처음 이 표에 적었던 "발 미끄러짐 0%"는 잘못 센 값이었습니다. 30 fps 로봇을 120 fps 시계로 세어 같은 자세가 반복됐고, 그래서 0.1 s 지속 조건이 성립할 수 없었습니다. 지금은 로봇 프레임 기준으로 셉니다.

결정이 필요한 것: `fallen`은 hard 플래그라서 넘어졌다 일어나기 클립을 FAIL로 만듭니다(Unitree·GMR 모두 31–34% 프레임). 데이터 오류가 아니라 동작 내용입니다. 태스크에 낙상·바닥 동작이 들어가면 soft로 바꾸거나 태스크별로 끄는 것이 맞습니다.

## 폴더 구조

```
khumanoid/          모션 로더, 공통 데이터 구조, QC (numpy만 사용 → Isaac Sim Python에서도 동작)
  retarget.py       GMR 연동 (GMR·mujoco는 함수 안에서만 import)
  analysis.py       모션 비교 지표 (시간 정렬, 관절 RMSE, 매끄러움, 발바닥 지표)
  compare.py        여러 포맷을 같은 로봇으로 불러오기 (리타게팅 캐시: data/cache/retarget/)
  io/cmu_frame_rates.json  CMU 시도별 실제 촬영 fps (cgspeed BVH 보정용)
tools/              retarget.py, compare_viewer.py, compare_report.py, qc_report.py, isaac_replay.py,
                    fetch_samples.py, make_samples.py, cmu_frame_rates.py
configs/qc.yaml     QC 임계값, 목표 시간
requirements.md     환경 재현 요구사항 (버전, 드라이버, 네트워크), environment.lock.txt: conda 잠금 파일
scripts/            install_isaacsim.ps1, setup_env.ps1, install_gmr.ps1
docs/research/      사전 조사 자료
tests/              pytest (python -m pytest tests; GMR이 없으면 리타게팅 E2E 테스트만 skip)
data/  reports/     (git 제외) data/raw 공개 샘플, data/retargeted 로봇 npz, QC·시뮬 검사 결과
```

## 알려진 한계와 다음 단계

- 사람은 스틱 피겨로만 표시합니다. SMPL-X 메시 표시는 아직 없습니다(UsdSkel 필요).
- 로봇 발바닥 높이는 발 링크 바운딩박스로 근사합니다. Isaac G1 USD의 발 박스는 GMR MJCF 충돌구보다 약 1.7 cm 낮아서, 리타게팅이 맞아도 최저점이 -2 cm 근처로 나옵니다.
- SMPL-X 경로는 AMASS SMPL-X N(중립 모델)으로만 확인했습니다. 성별 모델 파일(SMPL-X G)과 SMPL+H 파일은 리타게팅을 해 보지 않았습니다.
- GMR 결과는 바닥을 제약하지 않습니다. LAFAN1 춤·넘어졌다 일어나기에서 발이 바닥 아래 7–9 cm까지 내려가고 -2 cm 아래 프레임이 0.7–7.9%입니다(Unitree 0.03–1.6%). 평활화로는 바뀌지 않으므로, 바닥 동작을 쓰려면 IK에 바닥 제약을 넣거나 발 높이를 뒤처리해야 합니다.
- T-pose 설정의 로봇 자세 맞춤과 관절 중심 보정은 G1에만 정의되어 있습니다(`khumanoid/retarget.py`의 `TPOSE_CHAINS`, `JOINT_CENTERS`). LG 휴머노이드가 오면 MJCF를 GMR `params.py`에 등록하고, LAFAN1 형식 IK 설정과 이 두 표를 추가합니다.
- 손가락과 물체 접촉은 리타게팅하지 않습니다.
- 물리 실행 검증(PD 추종, 토크·자세 안정성)은 트래킹 정책(GMT 계열)이 생긴 뒤 붙일 예정입니다.
- 공개 5 h 데이터는 라이선스 제약으로 자체 촬영분(공개 동의서 확보)으로 채우는 것이 안전합니다(조사 자료 2.4절). 공개 샘플 중에서는 CMU만 공개 가능합니다.
