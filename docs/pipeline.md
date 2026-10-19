# 명령줄 파이프라인

저장소의 명령줄 도구(`tools/`)로 하는 일입니다: 리타게팅 → QC·유효시간 → Isaac 재생·검사·물리 → 비교. RetLens([retlens.md](retlens.md))와 브라우저 비교 뷰어는 같은 코어를 씁니다. 환경은 [setup.md](setup.md), 결과 기록은 [results.md](results.md), 데이터 폴더 구성은 [data.md](data.md)에 있습니다.

## 명령 한눈에

```powershell
conda activate k-humanoid

# 동작 확인용 합성 샘플 생성 (data/samples/): 사람 BVH(정상/글리치), G1 로봇 npz/csv
python tools\make_samples.py

# 공개 샘플 받기 (data/raw/, 출처·라이선스는 각 폴더의 SOURCE.md)
python tools\fetch_samples.py                  # cmu, cmu_fbx, unitree, lafan1 전부 (약 150 MB 다운로드, 남는 건 약 30 MB)
python tools\fetch_samples.py cmu              # CMU BVH 6개만 (2.3 MB)

# 1) 리타게팅: 사람 BVH / FBX / AMASS SMPL-X -> G1 npz (<out-dir>/<clip>_g1.npz + .json)
#    권장 설정: --smooth 6 (6 Hz 평활화) --swing-clearance 2 (움직이는 발을 바닥에서 2 cm 띄움). 둘 다 기본값은 끔
python tools\retarget.py data\raw\cmu_bvh --smooth 6 --swing-clearance 2 --out-dir data\retargeted\cmu_bvh
python tools\retarget.py data\raw\cmu_fbx --smooth 6 --swing-clearance 2 --out-dir data\retargeted\cmu_fbx      # FBX (Blender 필요)
python tools\retarget.py clip_stageii.npz --smooth 6 --swing-clearance 2 --smpl-model-dir models --out-dir data\retargeted\amass_cmu_smplx   # SMPL-X 바디모델 필요

# 2) QC + 유효시간 집계 (Isaac Sim 불필요, 수 초). --balance: 균형 지표·정적 불균형 플래그
python tools\qc_report.py data\samples --out reports\qc\samples
python tools\qc_report.py data\raw\cmu_bvh data\retargeted\cmu_bvh --urdf ..\GMR\assets\unitree_g1\g1_custom_collision_29dof.urdf --balance --out reports\qc\cmu_public
# 3) Isaac Sim GUI 재생
python tools\isaac_replay.py --human data\samples\synthetic_walk_glitch.bvh
python tools\isaac_replay.py --robot-motion data\samples\synthetic_g1_walk.npz
python tools\isaac_replay.py --human data\raw\cmu_bvh\143_11.bvh --robot-motion data\retargeted\cmu_bvh\143_11_g1.npz

# 4) 헤드리스 배치 검사: 전체 프레임 재생 + 스냅샷 + JSON
python tools\isaac_replay.py --human data\raw\cmu_bvh\143_11.bvh --robot-motion data\retargeted\cmu_bvh\143_11_g1.npz --headless --check-out reports\sim_check

# 5) 동영상 (사람·로봇 나란히, MP4. ffmpeg가 PATH에 없으면 GIF)
python tools\isaac_replay.py --human data\raw\cmu_bvh\143_11.bvh --robot-motion data\retargeted\cmu_bvh\143_11_g1.npz --video reports\videos\kinematic\143_11.mp4
python tools\isaac_replay.py --human data\raw\lafan1_bvh\dance1_subject1.bvh --robot-motion data\retargeted\lafan1_bvh\dance1_subject1_g1.npz --video reports\videos\internal_lafan1\dance1_30-50s.mp4 --start 30 --end 50

# 6) 물리 재생 (PhysX: 중력, 마찰 바닥, 관절 PD, 골반 보조 힘) -> <clip>_sim.npz + _sim.json
python tools\isaac_replay.py --robot-motion data\retargeted\cmu_bvh\143_11_g1.npz --physics --check-out reports\physics\cmu_bvh
python tools\isaac_replay.py --robot-motion data\retargeted\cmu_bvh\02_01_g1.npz --physics --assist 0     # 보조 힘 없이 (넘어지면 리셋하고 셈)
python tools\isaac_replay.py --human data\raw\cmu_bvh\143_11.bvh --robot-motion data\retargeted\cmu_bvh\143_11_g1.npz --physics --video reports\videos\physics\143_11_cmu_bvh.mp4
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
| `smplx-gmr` | 같은 파일을 GMR 자체 SMPL-X 로더·설정으로 처리합니다. 로봇 발끝 링크를 SMPL-X 발가락 관절에 맞춰서, AMASS CMU에서는 발이 3–5 cm 기울어 바닥을 뚫습니다([results.md](results.md)의 "BVH vs SMPL-X") |

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

설정별 비교(왜 6 Hz인지)는 [results.md](results.md)의 "평활화 설정 비교"에 있습니다.

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

효과(스윙 발 바닥 근접, 물리 넘어짐)는 [results.md](results.md)의 "스윙 발 높이 보정 효과"에 있습니다.

## Isaac 물리 재생 (물리 정합성)

비교 뷰어(viser)와 기본 Isaac 재생은 관절각대로 자세를 그리는 **기구학 재생**이라, 바닥을 뚫거나 공중에 떠 있거나 균형이 안 맞는 동작도 그대로 그립니다. `tools/isaac_replay.py --physics`는 Isaac Sim의 PhysX로 로봇을 실제로 시뮬레이션해 "로봇이 이 동작을 자기 발로 할 수 있는가"를 잽니다.

```powershell
python tools\isaac_replay.py --robot-motion data\retargeted\cmu_bvh\02_01_g1.npz --physics --check-out reports\physics\cmu_bvh
python tools\physics_report.py reports\physics --out reports\physics\summary.md
```

- **장면:** 중력 9.81 m/s², 마찰 있는 정적 바닥(정지 1.0, 운동 0.8), 240 Hz(모션 30 fps당 8스텝). 설정은 [configs/physics.yaml](../configs/physics.yaml)입니다.
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
- 판정 기준(하네스 > 체중 20% 프레임 5% 이하, 한계 초과 프레임 5% 이하, 넘어짐 0)은 `configs/physics.yaml`의 `report`에서 바꿉니다.

## 비교 뷰어 (브라우저)

`tools/compare_viewer.py`는 여러 모션을 같은 G1에 올려 브라우저에서 나란히 재생하고 수치로 비교합니다(viser 기반). 지표 계산은 `khumanoid/analysis.py`에 있습니다.

```powershell
# 같은 촬영의 BVH / FBX / AMASS SMPL-X(몸 메시)와 Isaac 물리 결과를 한 화면에
python tools\compare_viewer.py --body-mesh data\raw\cmu_bvh\143_11.bvh data\raw\cmu_fbx\143_11.fbx data\raw\amass_cmu_smplx\CMU\143\143_11_stageii.npz reports\physics\cmu_bvh\143_11_g1_sim.npz
# 같은 비교를 여러 클립에 대해 표로 (-g 그룹마다 첫 파일이 기준)
python tools\compare_report.py -g data\raw\cmu_bvh\02_01.bvh data\raw\amass_cmu_smplx\CMU\02\02_01_stageii.npz -g ... --out reports\compare\my_compare.md
# 같은 LAFAN1 클립: 우리 GMR(뷰어 기본 --smooth 6) vs Unitree 공식 리타겟 vs 권장 설정 리타겟(--smooth 6 --swing-clearance 2)
python tools\compare_viewer.py data\raw\lafan1_bvh\dance1_subject1.bvh data\raw\unitree_lafan1_g1\dance1_subject1.csv data\retargeted\lafan1_bvh\dance1_subject1_g1.npz
# -> 브라우저에서 http://127.0.0.1:8080
```

- **viser는 물리 시뮬레이터가 아닙니다.** 브라우저 3D 뷰어라서 관절각대로 자세를 그릴 뿐이고, 표의 발 미끄러짐·관통도 기하 계산입니다. 물리 정합성은 Isaac(PhysX)에서 계산합니다. 물리 모드를 켜거나, `isaac_replay.py --physics` 결과 npz를 원래 동작 옆에 놓고 봅니다.
- **입력, 물리 모드, 분석 지표**는 RetLens와 같습니다([retlens.md](retlens.md)). 물리 모드는 "재생" 탭 맨 위 버튼이나 시작할 때 `--physics`로 켭니다.
- **모션 고르기** ("모션" 탭): 경로를 입력하지 않고 클릭으로 고릅니다.
  - **폴더 → 파일:** `data/raw`, `data/samples`, `data/retargeted`, `data/uploads`, `reports`(물리 결과 `*_sim.npz`만) 아래의 모션 파일을 폴더별로 보여 줍니다. AMASS 체형 파일(`*_stagei.npz`)과 캐시 폴더는 뺍니다. 다른 폴더는 `--library DIR`로 추가합니다.
  - **이름 검색:** 이름 일부(예: `143_11`)를 넣으면 모든 폴더에서 찾습니다. 같은 촬영의 BVH, FBX, SMPL-X, 리타겟, 물리 결과가 한 번에 나옵니다. 그 번호로 시작하는 파일이 먼저 나옵니다(`05_02`가 `105_02`보다 앞).
  - **어떤 번호가 무슨 동작인지**는 [docs/cmu_motion_labels.md](cmu_motion_labels.md)에 있습니다. CMU 전체 2,548개 시도의 설명, 길이, 이 PC에 있는 형식과 동작 종류별 대표 시도를 담았고, `python tools\cmu_motion_index.py`로 다시 만듭니다.
  - **파일 열기 (내 PC):** 브라우저의 파일 선택 창으로 PC의 파일을 엽니다. 고른 파일은 `data/uploads/`에 복사해 엽니다. 같은 이름의 다른 파일이면 `_2`를 붙이고, 같은 파일이면 다시 복사하지 않습니다.
  - 경로를 직접 넣는 칸은 "경로 직접 입력" 아래에 있습니다. 추가한 모션은 "목록"에서 숨기거나 제거합니다.
- **동영상 저장** ("모션" 탭의 각 모션 아래 버튼):
  - `isaac_replay.py --human ... --robot-motion ... --video`와 같은 방식입니다. Isaac Sim에서 사람 스켈레톤(원본이 있으면)과 로봇을 나란히 녹화해 MP4로 저장합니다(960×540, 30 fps, ffmpeg가 없으면 GIF).
  - 로봇은 뷰어에 보이는 그 동작입니다(리타게팅·평활화·스윙 보정 설정 그대로). 물리 모드가 켜져 있으면 그 보조 힘 설정의 물리 시뮬레이션 결과를 녹화합니다(`--physics`).
  - 파일은 `reports/videos/viewer/<모션 이름>_kinematic.mp4` 또는 `_physics_x1.mp4`입니다(`--video-dir`로 바꿈). 같은 동작과 설정의 영상이 이미 있으면 다시 만들지 않습니다.
  - 다 되면 "동영상 내려받기" 버튼이 나타나서 브라우저로 받을 수 있습니다.
  - 녹화도 물리 계산과 같은 대기열에서 한 번에 하나씩 돕니다. 2.9초 클립이 약 1분 걸렸고, 대부분 Isaac 시작 시간입니다. "Isaac 작업 취소"로 멈춥니다.
- **3D:** 모션마다 다른 색의 G1을 나란히 또는 겹쳐서 보여 줍니다. 기본으로 각자의 시작 골반을 원점에, 진행 방향을 +x로 맞춥니다(소스마다 월드 좌표가 달라서). 리타게팅한 모션은 원본 사람을 로봇 크기로 줄여 옆에 그립니다(겹치기, 로봇 반투명 선택 가능). 사람은 기본이 막대 인형이고, SMPL-X 입력은 "사람 표시: 몸 메시"(또는 `--body-mesh`)로 몸 표면을 그립니다. 선형 블렌드 스키닝이며 자세별 보정 블렌드셰이프는 넣지 않았습니다. BVH·FBX에는 몸 표면 정보가 없어서 막대로만 그립니다.
- **재생:** 재생과 일시정지, 시간 슬라이더, ±1 프레임, 속도, 반복을 지원합니다. 모션별 시간 오프셋을 직접 넣거나, 기준 모션에 자동 정렬합니다(다리 관절각 차이가 가장 작은 오프셋).
- 기본으로 이 PC에서만 접속됩니다(`--host 127.0.0.1`). 다른 PC에서 보려면 `--host 0.0.0.0`을 쓰는데, 같은 네트워크의 누구나 열 수 있습니다.

## 지원 포맷

| 확장자 | 내용 | 로더 |
|---|---|---|
| `.bvh` | 스켈레톤 회전 애니메이션 (Vicon/OptiTrack/Xsens/Rokoko 내보내기, CMU, LAFAN1). 단위(cm/inch/m)는 키로 자동 추정. CMU cgspeed 변환본의 0번 T-pose 프레임은 자동으로 뺌 | `khumanoid/io/bvh.py` |
| `.fbx` | 스켈레톤 애니메이션 (MotionBuilder, Vicon Shogun, OptiTrack Motive, Xsens MVN, Mixamo, Blender). Blender 임포터로 읽음(Blender 4.5 필요). 단위가 어긋난 파일(cm 수치를 m로 저장)은 기준 자세 크기로 자동 보정. 테이크가 여럿이면 `take=` | `khumanoid/io/fbx.py` |
| `.c3d` | 광학 마커 궤적 (원시 데이터, 결측은 NaN). 뷰어·RetLens에서는 같은 촬영의 솔버 결과를 리타겟한 로봇 옆에 마커를 그림([retlens.md](retlens.md)의 "C3D 마커") | `khumanoid/io/c3d.py` (ezc3d), `khumanoid/markers.py` |
| `.npz` (AMASS) | SMPL / SMPL+H / SMPL-X 파라미터. 관절 계산에 바디모델 파일 필요 (`--smpl-model-dir` 또는 `SMPL_MODEL_DIR`) | `khumanoid/io/smpl.py` |
| `.npz` (로봇) | 프로젝트 표준 로봇 모션: `fps, joint_names, root_pos, root_quat_wxyz, dof_pos` (`tools/retarget.py` 출력) | `khumanoid/io/robot.py` |
| `.csv` | Unitree 리타게팅 csv (`x y z qx qy qz qw q1..qn`, 헤더 없음, 30 fps) | `khumanoid/io/robot.py` |
| `.pkl` | GMR(General Motion Retargeting) 출력 (직접 만든 파일만 열 것: pickle) | `khumanoid/io/robot.py` |

모든 로더는 Isaac Sim 좌표계(**Z-up, m, 쿼터니언 wxyz**)로 변환해서 돌려줍니다.
xyzw를 쓰는 포맷(Unitree csv, GMR)은 로더에서 변환합니다. 쿼터니언 순서는 포맷마다 다르니 [조사 자료 1.4절](research/mocap_survey.md)을 참고하세요.
## 검증(QC) 기준

임계값은 [configs/qc.yaml](../configs/qc.yaml)에서 조정합니다. 공개 스튜디오 데이터로 한 번 점검했고([results.md](results.md)의 "실데이터 QC 점검"), 자체 촬영 데이터가 들어오면 다시 확인해야 합니다.
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

## 알려진 한계와 다음 단계

- SMPL-X 몸 메시는 viser 장면(RetLens와 비교 뷰어)에만 있습니다. Isaac 재생에서는 사람을 스틱 피겨로만 그립니다(메시는 UsdSkel 필요).
- FBX는 Blender가 있어야 읽힙니다. 기준 자세는 아마추어의 rest pose를 T-pose로 가정합니다. A-pose로 바인딩된 리그(일부 Xsens·게임 리그)는 `--ref <T-pose 프레임>`을 주어야 합니다. 자체 촬영 장비의 FBX로는 아직 확인하지 않았습니다.
- 로봇 발바닥 높이는 발 링크 **충돌체**의 바운딩박스로 근사합니다(2026-10-16부터). 그 전에는 보이는 메시의 박스를 써서 약 1.7 cm 낮게 나왔습니다. 2026-10-15 검사의 발 최저점(-2.1~-2.8 cm, [results.md](results.md))은 그때 값입니다.
- SMPL-X 경로는 AMASS SMPL-X N(중립 모델)으로만 확인했습니다. 성별 모델 파일(SMPL-X G)과 SMPL+H 파일은 리타게팅을 해 보지 않았습니다.
- GMR 결과는 바닥을 제약하지 않습니다. LAFAN1 춤·넘어졌다 일어나기에서 발이 바닥 아래 7–9 cm까지 내려가고 -2 cm 아래 프레임이 0.7–7.9%입니다(Unitree 0.03–1.6%). 평활화로는 바뀌지 않으므로, 바닥 동작을 쓰려면 IK에 바닥 제약을 넣거나 발 높이를 뒤처리해야 합니다.
- CMU 143번 피험자의 리타겟(BVH·FBX·SMPL-X 모두)은 디딤발이 발끝 4–16° 들린 채라 뒤꿈치로만 섭니다(정상 −1~−4°, 02_01 SMPL-X도 +5°). 균형 지표의 정적 불균형 22–39%가 이것입니다. 원인은 발 방향 오프셋(T-pose 기준 자세의 발과 실제 디딤 자세의 발이 다름)으로 보이며, 디딤 구간의 발을 평평하게 맞추는 보정이 필요합니다.
- T-pose 설정의 로봇 자세 맞춤과 관절 중심 보정은 G1에만 정의되어 있습니다(`khumanoid/retarget.py`의 `TPOSE_CHAINS`, `JOINT_CENTERS`). LG 휴머노이드가 오면 MJCF를 GMR `params.py`에 등록하고, LAFAN1 형식 IK 설정과 이 두 표를 추가합니다.
- 손가락과 물체 접촉은 리타게팅하지 않습니다.
- 물리 재생은 정책 없는 PD 추종 + 골반 보조 힘이라, "로봇이 이 동작을 할 수 있는가"의 근사입니다. 최종 판정은 트래킹 정책(GMT·BeyondMimic 계열)을 학습해 보조 힘 없이 따라가는지로 해야 합니다.
- 공개 5 h 데이터는 라이선스 제약으로 자체 촬영분(공개 동의서 확보)으로 채우는 것이 안전합니다([조사 자료 2.4절](research/mocap_survey.md)). 공개 샘플 중에서는 CMU만 공개 가능합니다.
