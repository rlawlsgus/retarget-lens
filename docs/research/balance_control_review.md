# 균형 제어와 학습 데이터 처리 검토

2026-10-21. 질문: (1) 물리 재생에서 자주 넘어지면, 이 데이터로 학습한 실제 로봇도 넘어지는가? (2) 실제 G1의 균형 유지 알고리즘을 시뮬레이션에 넣어, 보조 힘 없이 켜고 끈 상태를 비교할 수 있는가? (3) 학습용 데이터는 어떻게 처리해야 하는가?

공개 자료(저장소 README·LICENSE, 논문, Unitree SDK 소스)를 조사하고, 이 PC에서 MuJoCo로 재생 실험을 해서 정리했습니다. 확인하지 못한 것은 "확인 안 됨"으로 적었습니다.

## 요약

1. **물리 재생에서 넘어진다고 학습한 로봇이 넘어지는 것은 아닙니다.** 지금의 물리 재생은 균형을 잡는 제어기가 없는 재생이고, 실제 로봇은 학습한 추적 정책이 균형을 잡습니다. 다만 데이터의 결함(발 끌림, 바닥 관통, 뒤꿈치로만 서기)은 학습한 정책도 넘어지게 하므로, 결함을 찾고 고치는 일은 여전히 필요합니다.
2. **실제 G1의 내장 균형 제어기는 가져올 수 없습니다.** 공개되지 않은 펌웨어이고 시뮬레이션 버전이 없으며, 애초에 관절 궤적을 받지 않습니다. 실제 로봇에서도 "내장 균형을 켠 채 전신 모캡 재생"은 할 수 없습니다. 그 자리에 들어가는 것이 학습한 추적 정책이고, 공개된 G1 범용 추적 정책으로 시뮬레이션에서 켜고 끄는 비교를 할 수 있습니다.
3. **학습 데이터는 세 단계로 거릅니다.** 운동학 정리 → 싼 물리 지표 → 추적 정책으로 따라가 보기(따라가지 못하는 클립은 고치거나 뺌, 필요하면 정책이 실제로 한 동작으로 바꿔 저장). 개루프 재생의 넘어짐 수로 클립을 버리지 않습니다.

## 1. 물리 재생의 넘어짐이 뜻하는 것

**지금의 물리 재생** (`tools/isaac_replay.py --physics`)은 리타겟 관절각을 높은 게인의 관절 PD로 그대로 따라갑니다(엉덩이·무릎 1500 N·m/rad). 넘어지려 해도 발 디딤이나 자세를 바꾸는 피드백이 없습니다. 그래서 골반 보조 힘(하네스)을 끄면(`--assist 0`) 깨끗한 데이터도 1–2초마다 넘어졌습니다([results.md](../results.md) "넘어짐 원인 진단 예시").

**시뮬레이터 탓이 아닙니다.** 같은 재생을 MuJoCo 3.11(GMR의 G1 MJCF)로 다시 만들어 봤습니다.
- CMU FBX 02_01·143_11·143_28을 하네스 없이 재생하면 0.6–1.1초에 처음 넘어집니다. Isaac 결과와 같습니다.
- 정책 수준 게인(엉덩이 100, 무릎 150, 발목 40)으로는 가만히 선 자세조차 1.3초마다 넘어집니다. 개루프로 서 있으려면 두 발목 강성의 합이 대략 m·g·h ≈ 230 N·m/rad를 넘어야 하기 때문입니다. 실제 G1 배포 게인은 이보다 훨씬 낮습니다(Unitree 예제 다리 100–150, 발목 40).

**실제 로봇은 추적 정책이 균형을 잡습니다.** 전신 모캡을 실제 로봇에서 따라가는 방법은 강화학습으로 만든 추적 정책입니다(BeyondMimic, GMT, TWIST, SONIC 등). 정책은 기준 동작과 자기 상태(IMU, 관절 속도)를 함께 보고, 기준에서 조금씩 벗어나며 균형을 잡습니다. 개루프 재생에서 넘어지는 클립도 정책은 대개 따라갑니다.

**그래도 데이터 결함은 학습한 정책도 넘어지게 합니다.**
- "Retargeting Matters"(GMR 논문): 같은 LAFAN1 춤을 네 가지 리타게터로 만들어 BeyondMimic을 학습했습니다. 바닥을 약 60 cm 뚫는 PHC 리타겟은 성공률 0%, GMR·Unitree 리타겟은 약 100%였습니다. 시작 프레임 하나를 바꾼 것만으로 64%가 100%가 된 클립도 있습니다.
- 우리 데이터에서 걸리는 것: 스윙 발이 바닥을 끄는 것(보정 전), CMU 143번 피험자 리타겟의 뒤꿈치로만 서기, 원본 CoM이 지지면 밖에 있는 구간, 엉덩이 토크 요구가 한계의 수 배인 구간.

**이번에 보신 넘어짐**은 RetLens 기본값(`--swing-clearance 0`, 스윙 발 보정 끔)으로 143_11을 돌린 결과입니다. FBX 2회(지지면 이탈), SMPL-X 1회(발끝 걸림), BVH 0회였습니다. 같은 클립을 `--swing-clearance 2`로 만든 2026-10-19 결과(`reports/physics/`)는 세 가지 모두 0회입니다.

## 2. 실제 G1의 균형 제어기

**공개되지 않았고 시뮬레이션에 넣을 수 없습니다.**
- G1의 걷기·서기 균형은 로봇 안쪽 제어 컴퓨터에서 도는 Unitree 펌웨어 서비스("sport")입니다. 소스도 가중치도 공개되지 않았습니다.
- Unitree의 시뮬레이터 `unitree_mujoco`는 README에 "저수준 개발만 지원"이라고 적혀 있고, 이 서비스를 돌리지 않습니다.
- 개발자 문서의 "PC1은 공식 서비스를 돌리며 개발을 지원하지 않는다"는 문구는 미러 사이트로만 확인했습니다(확인 안 됨).

**실제 로봇의 제어 단계** (`unitree_sdk2`, BSD-3):

| 단계 | 사용자가 보내는 것 | 균형 |
|---|---|---|
| 고수준 (`LocoClient`) | 속도, 서 있는 높이, 균형 모드(제자리 서기/걷기), 상태 번호, 미리 들어 있는 동작(손 흔들기, 펌웨어 동작 `550xxx`) | 내장 제어기 |
| 상체만 (`rt/arm_sdk`) | 상체 17관절(팔 7+7, 허리 3)의 목표 각도와 섞는 비율, 50 Hz | 내장 제어기가 다리로 균형·보행 |
| 저수준 (`rt/lowcmd`, 디버그 모드 또는 `SwitchToUserCtrl`) | 29관절 전부의 목표·게인·토크 | 없음 (사용자 제어기 몫) |

- 어느 단계도 "다리 관절 궤적을 따라가면서 균형을 잡는" 모드는 없습니다. 그래서 실제 로봇에서도 전신 모캡은 저수준 모드 + 사용자의 추적 정책으로만 재생합니다.
- Unitree도 춤 같은 전신 동작은 클립마다 학습한 추적 정책으로 합니다(`unitree_rl_lab`의 mimic 정책: Gangnam Style, Dance 102).
- 상체 모드는 "내장 균형 + 상체만 모캡"으로, 손 동작 위주의 작업에는 실제로 쓸 수 있는 길입니다.

## 3. 시뮬레이션에서 "균형 켬"으로 쓸 수 있는 제어기

공개된 G1 범용 추적 정책을 리타겟 클립에 연결하면, 같은 클립을 "제어기 없음(지금의 PD 재생, 하네스 끔)"과 "추적 정책 켬"으로 비교할 수 있습니다. 저장소 README·LICENSE·파일을 직접 확인한 결과입니다.

| 제어기 | 하는 일 | DoF | 라이선스 | 사전학습 가중치 | 이 PC (Windows) |
|---|---|---|---|---|---|
| **GMT** (General Motion Tracking) | 처음 보는 클립도 따라가는 범용 추적 | 23 | 코드 Apache-2.0, README: "제공 모델은 연구용" | `pretrained.pt` 7.9 MB (TorchScript) | **가능.** MuJoCo 재생 코드가 mujoco·torch·numpy만 씀. 지금 conda 환경으로 설치 없이 돌림. 입력이 GMR pkl 형식 |
| **ProtoMotions G1 추적기** (NVIDIA, BONES-SEED로 학습) | 범용 추적 | 29 | 코드 Apache-2.0, 가중치 NVIDIA Open Model License(상업 사용 가능, 출처 표기) | ONNX (git LFS) | **가능.** MuJoCo CPU 테스트 스크립트가 있음. onnxruntime 설치와 동작 파일 형식 변환이 필요. 미래 프레임 4개(0.16 s)만 봄 |
| TWIST2 (GMR 저자) | 범용 추적, GMR 데이터로 학습 | 29 | MIT | ONNX 3 MB | 어댑터 필요. 공식 동작 서버가 isaacgym(리눅스 전용)을 불러오고 Redis가 필요 |
| RoboJuDo | 위 정책들을 한 MuJoCo 틀에서 돌리는 도구 | – | LICENSE 파일 CC BY 4.0, README 배지는 CC BY-NC 4.0 (불일치) | GMT·TWIST·ProtoMotions 등 동봉 | Windows에서 시험했다고 적힌 유일한 도구 |
| AMO | 다리는 학습한 균형, 상체·몸통 자세는 명령으로 받음 | 29 | Apache-2.0 | TorchScript | 가능. "내장 균형 + 상체 모캡"(실제 G1 상체 모드)에 가장 가까운 비교 |
| NVIDIA GEAR-SONIC | 가장 강한 범용 추적(스튜디오 모캡 약 700 h) | 29 | 코드 Apache-2.0, 가중치 NVIDIA Open Model License | ONNX (약 870 MB) | 불가. Linux + TensorRT C++ 배포 |
| unitree_rl_gym `motion.pt` | 다리 12관절 보행 정책 | 12 | BSD-3 | 142 KB | 상체가 없어 모캡 재생에 쓸모가 적음 |

- **클립마다 학습해야 하는 것**(BeyondMimic/whole_body_tracking, unitree_rl_lab·unitree_rl_mjlab mimic, ASAP, PBHC)은 처음 보는 클립에 바로 쓸 수 없습니다. 나중의 학습 경로입니다.
- **H1 전용이거나 가중치가 없는 것**(HOVER, OmniH2O/H2O, HumanPlus, UniTracker)은 제외했습니다.
- **모델 기반 안정화도 시험했습니다**(다운로드 없이, MuJoCo). PD 재생 위에 디딤 다리의 발목을 capture point 오차만큼, 엉덩이를 골반 자세 오차만큼 보정하는 방식입니다.
  - 가만히 선 자세는 넘어지지 않게 됐습니다(10초에 7회 → 0회).
  - 걷는 클립은 첫 넘어짐을 0.07–0.23초 늦출 뿐이었고, 토크 포화 프레임이 15–80%로 늘었습니다. 발목으로 옮길 수 있는 압력 중심이 옆으로 ±3 cm 정도뿐이기 때문입니다.
  - 그래서 걷는 동작의 판정에는 쓸 수 없습니다.

### 비교 실험 (2026-10-21 구현)

`tools/policy_replay.py`로 만들었습니다. 사용법은 [pipeline.md](../pipeline.md) "균형 켬/끔 비교", 결과는 [results.md](../results.md) 맨 위에 있습니다.

| 조건 | 제어 | 보는 것 |
|---|---|---|
| 끔 | 지금의 PD 재생과 같은 개루프 PD(`configs/physics.yaml` 게인), 하네스 없음 | 넘어짐 (참고용: 깨끗한 데이터도 넘어짐) |
| 켬 | GMT 범용 추적 정책, 하네스 없음 | 넘어짐, 관절·몸 위치 추적 오차, 정책이 기준을 바꾼 정도, 토크 한계 |
| (보조) | Isaac 물리 재생, 하네스 켬 (RetLens 물리 모드) | 보조 힘, 토크 요구, 넘어짐 원인 |

- **MuJoCo에서 합니다.** 공개 정책은 모두 MuJoCo로 검증되어 나왔고, 10.9초 클립이 CPU에서 2–3초 걸립니다(Isaac은 약 1분 15초).
- **GMT 이식이 맞는지 확인했습니다.** 저자들의 `sim2sim.py`를 numpy로 옮겼고, 같은 시작 상태에서 3초 동안 저자 코드와 관절각·루트 위치가 똑같이 나왔습니다. 기준 관측값은 2×10⁻⁶ 안에서 같습니다.
- **넘어짐 기준:** 기울기·높이 기준만 씁니다(원본보다 60° 기울기, 0.3 m 아래, 원본보다 0.25 m 낮음). "골반이 원본에서 50 cm 벗어남"은 정책이 경로를 조금씩 벗어나는 것까지 넘어짐으로 세므로 쓰지 않습니다.
- **GMT의 23 DoF**는 29 DoF G1에서 손목 6관절을 고정한 것입니다. 허리 3관절은 그대로라 우리 리타겟에서 손목만 빼고 넣습니다.
- **결과 요약:**
  - CMU 17클립에서 제어기 없이는 모든 클립이 0.5–1.5초 안에 넘어졌습니다.
  - GMT는 34번 중 33번을 넘어지지 않았고, 한 번은 걷는 도중 자세로 바로 시작한 탓이었습니다.
  - 그러니 물리 재생에서 자주 넘어지는 것 자체는 학습한 로봇이 넘어진다는 뜻이 아닙니다. 판정은 추적 정책으로 하고, 클립 앞뒤에 정지 자세를 붙이는 것이 좋습니다.
- 다음으로 할 수 있는 것: RetLens 물리 모드에 "균형 제어: 없음 / 보조 힘 / 추적 정책" 선택을 붙여, 지금의 진단·지표·동영상과 함께 보기.

## 4. 학습용 데이터 처리 (제안)

2024–2026년 연구에서 공통된 흐름은 "운동학 정리 → 싼 물리 필터 → 추적 정책으로 판정(sim-to-data) → 필요하면 물리 보정"입니다. 예:
- H2O는 리타겟한 AMASS 10k 클립에서 추적 정책이 따라간 약 8.5k만 남겼습니다.
- GMT는 규칙 기반과 정책 기반 필터를 거쳐 8,925클립(33.1 h)을 남겼습니다.
- ExBody2는 CMU 클립을 추적 오차로 순위를 매겨 기준 이하만 썼습니다.

우리 파이프라인에 맞추면:

1. **받기:** FBX와 라벨된 C3D를 함께 받습니다. 보정 자세·ROM 구간을 잘라내고 단위·위쪽 축·기준 자세(A/T)를 확인합니다. 원본 120 Hz를 보관합니다.
2. **사람 QC:** 지금의 결측·튐·관통·떠 있음·미끄러짐 검사.
3. **리타겟 + 운동학 정리:**
   - GMR, `--smooth 6`, `--swing-clearance 2`(지금 권장 설정).
   - 추가할 것: 접지 라벨(발 속도 0.15 m/s·높이 0.1 m 이하, ProtoMotions 기준), 디딤발 고정과 평평하게 맞추기(CMU 143번 뒤꿈치 서기 문제), 관절 한계 98% 안, 클립 앞뒤에 정지 자세 붙이기(HuB·Retargeting Matters: 시작 자세가 성공률을 크게 바꿈).
4. **싼 물리 지표:** 지금의 하네스 켠 물리 재생과 균형 지표(CoM 지지면 거리, 정적 불균형, 보조 힘, 토크 요구). 문제 표시에만 쓰고, 개루프 넘어짐 수로 버리지 않습니다. 참고 기준: PHUMA 골반-지지면 6 cm, HuB CoM-디딤발 0.2 m, PBHC CoM-CoP 0.1.
5. **추적 정책으로 판정:** 범용 추적 정책으로 클립마다 돌려 성공 여부·추적 오차·넘어짐 원인을 남기고 "통과 / 고쳐서 다시 / 제외"로 나눕니다.
6. **(선택) 물리 보정:** 추적 정책이 시뮬레이션에서 실제로 한 동작을 새 기준 동작으로 저장합니다(`_sim.npz` 경로는 이미 있음). OmniTrack은 이렇게 해서 LAFAN1 바닥 관통 20.3% → 0%, 학습한 정책 성공률 88.2% → 92.6%를 보고했습니다.
7. **내보내기:** Unitree csv(30 fps, 루트 xyz + 쿼터니언 xyzw + 29관절), GMR pkl, BeyondMimic npz(50 Hz, 몸 링크 자세 포함). 접지 라벨·QC·판정 메타데이터를 함께 냅니다.
8. **학습:** 클립별 추적 정책(BeyondMimic 계열, unitree_rl_lab mimic) 또는 범용 추적기 미세조정. Isaac Lab이나 MuJoCo Warp가 도는 리눅스 GPU 머신이 필요합니다. RTX 3070 8 GB로는 빠듯할 것으로 봅니다(확인 안 됨).

- 너무 엄격하게 거르면 데이터가 단순해집니다(ExBody2). TWIST는 자체 촬영한 잡음 있는 모캡 0.5 h를 섞어 처음 보는 동작의 추적이 나아졌다고 보고했습니다.
- 데이터 품질 지표는 추적 성공률(몸 높이 차 0.25 m 또는 관절 평균 위치 차 0.5 m 기준), MPJPE, 바닥 관통·떠 있음·미끄러짐 비율을 씁니다.

## 5. 촬영 업체에 요청할 것

- **결과물:**
  - 라벨·공백 채움을 마친 C3D. 가능하면 채우기 전 원본 C3D도.
  - 배우 체형의 솔빙 스켈레톤으로 푼 FBX. 게임 캐릭터 리그로 옮긴 것이 아니어야 합니다. 모든 테이크에서 같은 골격 템플릿과 본 이름을 씁니다.
  - 가능하면 BVH와 공통 체형 버전(BONES-SEED 방식).
- **촬영 설정:** 원본 120 Hz 이상, 다시 샘플링하지 않음, 타임코드.
- **테이크마다 적어 줄 것:**
  - 보정 자세(Vicon Shogun 최신 버전은 A-pose로 보정함).
  - 배우별 ROM 테이크.
  - 단위·위쪽 축.
  - 바닥 높이 0.
  - 발 외 접촉(손 짚기, 기대기)과 소품.
- **있으면 좋은 것:** 동기화된 참고 영상, 힘판(발 접지 시점의 정답).

## 출처

- Unitree: [unitree_sdk2](https://github.com/unitreerobotics/unitree_sdk2) (`g1_loco_client.hpp`, `example/g1/high_level/g1_arm7_sdk_dds_example.cpp`), [unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco), [unitree_rl_lab](https://github.com/unitreerobotics/unitree_rl_lab), [unitree_rl_gym](https://github.com/unitreerobotics/unitree_rl_gym), [unitree_rl_mjlab](https://github.com/unitreerobotics/unitree_rl_mjlab), [unitree_sim_isaaclab](https://github.com/unitreerobotics/unitree_sim_isaaclab), [xr_teleoperate](https://github.com/unitreerobotics/xr_teleoperate).
- 추적 정책: [GMT](https://github.com/zixuan417/humanoid-general-motion-tracking), [ProtoMotions](https://github.com/NVlabs/ProtoMotions), [TWIST2](https://github.com/amazon-far/TWIST2), [TWIST](https://github.com/YanjieZe/TWIST), [RoboJuDo](https://github.com/HansZ8/RoboJuDo), [AMO](https://github.com/OpenTeleVision/AMO), [GR00T-WholeBodyControl / SONIC](https://github.com/NVlabs/GR00T-WholeBodyControl), [BeyondMimic whole_body_tracking](https://github.com/HybridRobotics/whole_body_tracking), [ASAP](https://github.com/LeCAR-Lab/ASAP), [PBHC](https://github.com/TeleHuman/PBHC), [Humanoid-GPT](https://github.com/GalaxyGeneralRobotics/Humanoid-GPT), [OpenTrack](https://github.com/GalaxyGeneralRobotics/OpenTrack), [BFM-Zero](https://github.com/LeCAR-Lab/BFM-Zero).
- 데이터 처리: H2O/OmniH2O(human2humanoid), ExBody2, GMT 논문, PBHC(KungfuBot), PHUMA, OmniTrack, HuB, OmniRetarget, "Retargeting Matters"(GMR), SONIC, BONES-SEED, KDMR.
