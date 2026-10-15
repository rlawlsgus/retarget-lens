# Human MoCap 기반 전신 모션 데이터셋 구축 사전 조사

- 과제: K-온디바이스 휴머노이드 (NC AI + 고려대 IIIXR) — 1차년도 가정환경 장기(long-horizon) loco-manipulation 모션 데이터셋
- 작성일: 2026-10-15 (웹 조사 기준일). 데이터셋·영상은 다운로드하지 않았고, 공식 페이지·저장소·라이선스 문서만 확인함
- 표기
  - **[미확인]**: 1차 출처(공식 페이지, 저장소, 라이선스 원문)에서 확인하지 못한 항목
  - O / X / △: 있음·허용 / 없음·불가 / 부분·조건부
- 이 문서는 법률 자문이 아니다. 공개(5 h) 데이터 지정 전에 법무 검토를 반드시 받는다.

---

## 0. 핵심 요약

1. **정본(canonical) 포맷**은 3계층으로 둔다.
   - `raw/`: 벤더 원본(.tak/.x2d/.mcp/.mvnx)과 라벨링된 C3D. 변경 불가로 보관한다.
   - `human/`: **AMASS SMPL-X npz 키 이름 그대로**인 SMPL-X 파라미터. Z-up, m 단위.
   - `robot/<robot>/<retarget_ver>/`: 로봇 관절공간 npz. BeyondMimic 및 Isaac Lab 2.x 호환 키를 쓰고, 쿼터니언은 **wxyz로 명시**한다.
   - 여기에 JSON sidecar 메타데이터를 붙인다(1.5절).
2. **쿼터니언 순서가 가장 큰 버그 원인이다.**
   - Isaac Sim, USD, MuJoCo, Isaac Lab 2.x는 wxyz이고 Unitree CSV, GMR pkl, PHC는 xyzw이다.
   - **Isaac Lab 3.0은 xyzw로 바뀌었다.** 메타데이터에 `quat_convention`을 반드시 기록한다.
3. **가정 loco-manipulation에 직접 맞는 공개 MoCap**은 다음과 같다.
   - 큰 물체 운반·밀기: OMOMO(~10 h), CORE4D
   - 실제 주방·세탁, 관절 가구: ParaHome(8.1 h)
   - 100개 실내 씬, 앉기·눕기·개폐: TRUMANS(15 h+)
   - 다단계 요리·정리: HUMOTO(2.2 h)
   - 박스·의자 들기·운반: BEHAVE
   - 정밀 파지: GRAB, ARCTIC
   - 집 안 일상 이동·시선: Nymeria(300 h)
   - 2026 신규: ACE-Data-0(150 h, 200 m² 아파트, 다단계 sub-goal; 데이터 파일은 아직 미공개)
4. **라이선스 적신호.** 대부분 비상업(NC) 또는 재배포 금지다.
   - AMASS와 AMASS 파생물(HumanML3D, AMASS→G1 리타겟, PHUMA 일부), GRAB, ARCTIC, InterCap, BEHAVE, EgoBody, TRUMANS, Embody3D, ACE-Data-0, BONES-SEED는 공개 5 h에 **사용 불가**다.
   - LAFAN1은 **CC BY-NC-ND**다. 리타겟본(Unitree CSV 포함)도 공유할 수 없다.
5. **바디모델 자체가 리스크다.** SMPL/SMPL-X 모델 라이선스와 MoSh++/SOMA는 **비상업 연구 전용**이다.
   - 기업(NC AI)이나 LG 제품으로 이어지는 사용에는 Meshcapade/MPI 상업 라이선스 검토가 필요하다.
6. **공개 가능 후보는 소수다.**
   - **CMU 원본(ASF/AMC, C3D)**: 상업 사용과 재배포가 허용되고, 데이터 자체 판매만 금지된다. AMASS의 SMPL 피팅본이 아니라 원본을 써야 한다.
   - **CORE4D**: CC BY 4.0
   - **MMHOI**: CC BY-SA 4.0
   - **100STYLE**: CC BY 4.0, 보행 스타일 BVH
   - **결론: 공개 5 h는 자체 촬영분(공개 동의서 확보)으로 채우는 것이 가장 안전하다.**
7. **리타겟·검증 툴체인 권장안**
   - LG 로봇 모델이 도착하기 전에는 **Unitree G1(29 DoF)과 H1-2를 프록시**로 쓴다.
   - 리타겟: **GMR**(MIT; SMPL-X, BVH, FBX, Xsens 입력)
   - 손: **dex-retargeting**을 2차 패스로 돌린다.
   - Isaac Sim 검증: **BeyondMimic `csv_to_npz.py` 방식의 kinematic replay**를 LG용으로 포크한다.
   - 사람 메시 오버레이: UsdSkel SkelAnimation
8. **버전 현황(2026-10)**
   - Isaac Lab 2.3.2(Isaac Sim 5.1)가 2.x 마지막 릴리스다.
   - Isaac Lab 3.0.0-EA(Isaac Sim 6.1)가 나와 있고, GA는 2026-10월 말 목표다.
   - BeyondMimic과 SONIC은 Isaac Lab 2.x 계열이고, ProtoMotions v3는 Isaac Lab 3.0/Isaac Sim 6.0을 쓴다.
   - 계획서의 "Isaac Sim 5.x / Isaac Lab 2.x"는 당장은 유효하다. 다만 3.0 이전 계획을 세워 둔다.

---

## 1. MoCap 데이터 포맷

### 1.1 인간(소스) 측 포맷

| 포맷 | 저장 내용 | 회전 / 루트 | 좌표·단위·fps | 손 / 접촉 | 대표 출처 | 변환 도구 | 우리 파이프라인 적합도 |
|---|---|---|---|---|---|---|---|
| **BVH** | 텍스트. `HIERARCHY`(ROOT/JOINT/End Site, OFFSET, CHANNELS)와 `MOTION`(Frames, Frame Time) | 관절별 Euler(도). 채널 선언 순서가 회전 순서다(예: Zrotation Xrotation Yrotation). 루트는 6채널(위치+회전). 레스트 포즈 회전 정보가 없다 | 단위 필드가 없다(LAFAN1은 cm). 관례상 Y-up. `Frame Time`=1/fps | 손가락 관절은 스켈레톤에 있으면 가능. 접촉 X | LAFAN1, CMU(cgspeed 변환본), 100STYLE, BONES-SEED(SOMA 77관절, 120 fps), HiPHI(55관절, ZXY), Xsens/Motive/Noitom/Rokoko/Nokov export | GMR(`bvh_to_robot.py --format lafan1/nokov`, Xsens BVH), Blender, LAFAN1 `extract.py` | 중. 원시 스켈레톤 교환용으로 좋다. SMPL-X로 가려면 별도 IK 피팅이 필요하다. GMR로 로봇에 직접 리타겟할 수 있다 |
| **FBX** | 바이너리/ASCII, Autodesk 독점. 노드 그래프(스켈레톤, 메시), 스킨, 블렌드셰이프, AnimStack/AnimCurve | Euler(`RotationOrder`, 기본 XYZ)에 pre/post rotation, pivot이 더해져 복잡하다 | `FbxSystemUnit`(기본 cm), `FbxAxisSystem`, 시간 모드 | 손·얼굴 O, 접촉 X | Motive/Shogun/MVN/Rokoko export, Mixamo, HUMOTO(Mixamo 리그) | FBX SDK(Python), Blender(7.1+ 바이너리만, 본 축 차이, 애니메이션 지원은 "minimal"), Omniverse Asset Converter(FBX→USD) | 하~중. 벤더 export와 Isaac 시각화용. 정본으로는 부적합하다 |
| **C3D** | 헤더, 파라미터(POINT:LABELS/RATE/UNITS/SCALE, ANALOG:RATE), 데이터. 3D 마커 궤적과 residual, 아날로그(포스플레이트, EMG) | 회전 없음(점만) | 보통 mm. Z-up이 일반적이지만 OptiTrack은 Y-up. `POINT:RATE` | 손가락 마커 가능. 접촉은 포스플레이트로 추정 | Vicon Nexus/Shogun, OptiTrack Motive, KIT, SFU, AMASS 원천 | ezc3d(읽기/쓰기, points 4×N×T), `c3d`(py). **SOMA**(마커 자동 라벨링)를 거쳐 **MoSh++**(마커→SMPL-X, `*_stageii.pkl`)로 간다. 둘 다 비상업 라이선스 | **상(원본 보관)**. AMASS와 같은 경로로 SMPL-X를 얻는다 |
| **TRC / MOT·STO** | OpenSim 텍스트. TRC는 마커 위치(DataRate, Units 헤더), MOT/STO는 관절 좌표(기본 도) | MOT는 OpenSim 모델 좌표 | mm(TRC) | – | Motive(Body 라이선스), AddBiomechanics | OpenSim IK | 하. 생체역학 분석을 할 때만 |
| **Xsens MVNX** | XML. 프레임별 23세그먼트 `orientation`(쿼터니언), position/velocity/acceleration/angularVelocity, `jointAngle`(ZXY, 도), `centerOfMass`, 센서 raw, **`footContacts`**(L/R Heel/Toe 4개 boolean). 앞 3프레임은 config(identity, tpose, tpose-isb) | 세그먼트 global 쿼터니언(scalar-first로 추정 [미확인]) | SI 단위. 전역 프레임 정의는 [미확인](MVN 매뉴얼 §14.4 확인 필요) | 장갑을 쓰면 손가락 O. **발 접촉 플래그 O** | Xsens MVN Analyze/Animate, Nymeria(Xsens MVN Link), ParaHome(Xsens 수트) | MVN에서 BVH/FBX/C3D export. GMR(Xsens BVH 오프라인, MVN UDP 실시간). MVNX→SMPL-X 공식 도구는 [미확인] | **상(IMU 촬영 시)**. 발 지지 상태 라벨 초기값으로 바로 쓸 수 있다 |
| **OptiTrack Motive 네이티브** | `.tak`(원본 테이크). CSV/C3D(Tracker·Body 라이선스), FBX/BVH/TRC(Body 전용) export. CSV에는 마커, rigid body, 본 정보가 들어 있다 | 쿼터니언 또는 6가지 Euler 순서 중 선택 | Y-up 오른손 좌표, 단위 선택 | 손가락 마커셋. **물체 rigid body 6DoF** | 자체 촬영, ACE-Data-0 | Motive Batch Processor, GMR(Motive FBX 오프라인·스트리밍) | **상**. 사람과 물체를 같은 시간축으로 기록한다 |
| **Vicon Shogun 네이티브** | Live: `.x2d`(2D 카메라 원본)와 `.mcp`(실시간 솔브). Post: 재처리. `.vsk`(스켈레톤), `.vss`(솔버) | – | mm | 손가락 솔빙 O | 자체 촬영, OMOMO, GRAB, BONES-SEED | FBX export(FBX 지원 fps만). C3D/BVH/CSV export는 일반적이지만 공식 목록은 [미확인] | 상 |
| **SMPL / SMPL-H / SMPL-X 파라미터** | 형상 `betas`, 관절 axis-angle, 루트 이동. SMPL 24관절(72), SMPL-H 52관절(156), SMPL-X 55관절(165, jaw·eye 포함), expression | 로컬 axis-angle(rad). `root_orient` 분리 | AMASS는 **Z-up, +Y forward**, m | SMPL-H/X는 MANO 손 O. 접촉은 별도 계산 | AMASS, GRAB, OMOMO, ParaHome, TRUMANS, Motion-X, CORE4D 등 | MoSh++, SMPLify-X, `smplx`(`transfer_model`로 SMPL↔H↔X 변환), aitviewer, Blender SMPL-X add-on | **최상(통합 표현)**. 모델 라이선스는 1.6절 참조 |
| **HumanML3D 263-D** | 루트 회전속도 1, 선속도(XZ) 2, 높이 1, ric(21×3) 63, 6D 회전(21×6) 126, 관절 속도(22×3) 66, 발 접촉 4 | 6D(관절), 루트는 속도 | 20 fps, Y-up, +Z 정면 | 손 X | HumanML3D | AMASS에서 재생성 스크립트 | 하. 학습 특징용이며 손실 변환이라 리타겟에는 부적합하다 |
| **USD / UsdSkel** | `Skeleton`(joints, bind/rest)과 **`SkelAnimation`**(joints, translations float3[], rotations quatf[], scales half3[], blendShapeWeights). time-sampled | 쿼터니언 **wxyz** | `timeCodesPerSecond`, metersPerUnit, upAxis. USD 각도 단위는 도 | 손가락·블렌드셰이프 O | Omniverse 캐릭터, BONES-SEED(SOMA USD) | Asset Converter(FBX→USD; Isaac Sim 5.1에서 FBX 리그 관절 미인식 사례 보고), Blender USD export, `pxr.UsdSkel`로 직접 작성 | 중. **사람 메시 시각화 전용**. PhysX articulation(로봇)은 구동하지 못한다 |

추가 참고:

- **NVIDIA SOMA / SOMA-X** (arXiv 2603.16858, 2026-03)
  - SMPL-X, MHR, Anny 등을 하나로 묶는 바디모델 추상화 레이어다. 77관절 `somaskel77`을 쓴다.
  - BONES-SEED, Kimodo, soma-retargeter가 SOMA BVH를 쓴다. SMPL-X 대안으로 지켜볼 만하다.
  - SOMA-X 라이선스는 [미확인].
- **BABEL 라벨 형식** `{raw_label, proc_label, act_cat, seg_id, start_t, end_t}`은 세그먼트 라벨 설계 참고용으로 좋다.

### 1.2 SMPL 계열 파일 상세 (AMASS npz)

| 구분 | 키 (검증됨) | 비고 |
|---|---|---|
| AMASS SMPL+H(G) | `poses`(N,156), `trans`(N,3), `betas`(16), `dmpls`(N,8), `gender`, **`mocap_framerate`** | `poses`[:, :3]=root, [3:66]=body, [66:]=hands(90) |
| AMASS SMPL-X(2022~) | `gender`, `surface_model_type`(=smplx), **`mocap_frame_rate`**, `mocap_time_length`, `trans`, `poses`(N,165), `root_orient`[0:3], `pose_body`[3:66](63), `pose_jaw`[66:69], `pose_eye`[69:75](6), `pose_hand`[75:](90), `betas`·`num_betas`, (선택) `expression`, `dmpls`, `markers_latent`, `latent_labels` | 파일명 `*_stageii.npz`. 배포 파일의 betas 개수는 [미확인](MoSh++ 기본값 16) |
| MoSh++ stage-ii pkl | `fullpose`, `trans`, `betas`, `expression`, `markers_latent`, `stageii_debug_details`(cfg, mocap_frame_rate, markers_obs/sim 등) | `moshpp_conf.yaml`: `mocap.unit: mm`, `surface_model.type: smplx`, 기본 `optimize_fingers: false` |
| SMPLify-X 결과 pkl | `global_orient`, `body_pose`, `left/right_hand_pose`, `jaw_pose`, `leye/reye_pose`, `betas`, `expression`, `transl` | VPoser를 쓰면 `body_pose`가 **32-D latent**다(함정) |

로더 주의사항:

- **키 이름 차이**: SMPL+H는 `mocap_framerate`, SMPL-X는 `mocap_frame_rate`다. 읽을 때 둘 다 받아야 한다.
- **GMR**은 `pose_body`, `root_orient`, `trans`, `betas`, `gender`만 읽는다. 손은 0으로 두고, 키는 `1.66 + 0.1*betas[0]`로 추정한다.
- **PHC/ASAP 로더**는 `skip = fps//30`으로 정수 스트라이드를 한다. 100 fps 입력이면 실제로 약 33 fps가 되는데 30으로 표기되는 버그 위험이 있다. 리샘플링은 lerp/slerp 보간으로 한다.

### 1.3 로봇(리타겟 결과) 측 포맷

| 포맷 | 레이아웃 (검증됨) | 쿼터니언 | fps | 사용처 |
|---|---|---|---|---|
| **Unitree LAFAN1 retarget CSV** | 헤더 없음. 행마다 `[root xyz, root quat, joint angles]`. G1 29관절=36열, H1-2 27관절=34열, H1 19관절=26열 | **xyzw** | 30 | BeyondMimic, mjlab 입력. HF: `lvhaidong/LAFAN1_Retargeting_Dataset`(공식 unitreerobotics 경로는 401) |
| **GMR pkl** | `fps`(30으로 정렬), `root_pos`(N,3), `root_rot`(N,4), `dof_pos`(N,D, MJCF 관절 순서), `local_body_pos`=None, `link_body_list`=None | **xyzw**(코드 주석 "wxyz→xyzw") | 30 | GMR, TWIST/TWIST2, **GMT**(`utils/motion_lib.py`가 같은 키를 읽음), MimicKit(변환기 있음). `batch_gmr_pkl_to_csv.py`로 CSV 변환(30 fps 초과 시 보간 없이 stride) |
| **BeyondMimic npz** | `csv_to_npz.py`가 Isaac Sim에서 kinematic replay를 돌려 기록: `fps`, `joint_pos`, `joint_vel`, `body_pos_w`, `body_quat_w`, `body_lin_vel_w`, `body_ang_vel_w` | wxyz(Isaac Lab 2.x) | 입력 30, 출력 50 | Isaac Lab tracking 학습. W&B registry에 업로드됨(로컬 저장은 포크해서 수정 필요) |
| **Isaac Lab humanoid_amp npz** | `fps`, `dof_names`, `body_names`, `dof_positions`/`dof_velocities`(N,D), `body_positions`(N,B,3), `body_rotations`(N,B,4), `body_linear/angular_velocities`(N,B,3) | **wxyz** | 파일별 | Isaac Lab AMP 예제. `motion_viewer.py`는 matplotlib 점 그래프 뷰어일 뿐 Isaac 재생이 아니다 |
| **PHC AMASS pkl** | `pose_quat_global`, `pose_quat`, `trans_orig`, `root_trans_offset`, `beta`, `gender`, `pose_aa`(24×3), `fps` | xyzw(SciPy, 추정) | – | PHC |
| **ASAP/HumanoidVerse 로봇 pkl** | `root_trans_offset`, `pose_aa`, `dof`, `root_rot`, `smpl_joints`, `fps`(30 고정) | xyzw | 30 | ASAP |
| **poselib SkeletonMotion** | `rotation`(local), `root_translation`, `skeleton_tree`, `global_velocity`, `fps` | xyzw | 파일별 | IsaacGymEnvs AMP, PHC 계열 |
| **ProtoMotions** | AMASS npz를 `convert_amass_to_proto.py`로 `.motion`(FK, 속도, 접촉, 지면 정렬)으로 바꾸고, 다시 `.pt` MotionLib으로 패키징(`rigid_body_pos/rot`, `dof_pos`, `contacts`, `motion_dt` 등) | xyzw(추정) | 30 | ProtoMotions v3 |
| **PHUMA npy** | `root_trans`, `root_ori`, `dof_pos`, `fps` | xyzw | 파일별 | G1, H1-2 |
| **OmniRetarget npz** | `fps`, `qpos`(36 = base 7 + 29 관절, 물체가 있으면 +7) | – | – | holosoma |
| **Kimodo G1 CSV** | MuJoCo qpos 36개(root xyz, root quat, 29관절) | **wxyz** | – | Kimodo 출력 |
| **SONIC(GR00T-WBC)** | 학습 입력은 joblib pkl(root trans, `pose_aa`, MuJoCo 순서 `dof`, root quat, fps). 배포 참조는 50 Hz CSV 폴더(`joint_pos.csv`는 Isaac Lab 순서, `body_quat.csv`는 wxyz) | 혼재 | 50 | SONIC |

### 1.4 쿼터니언·좌표 규약 요약

| 위치 | 순서 |
|---|---|
| Isaac Sim Core / USD / Isaac Lab 2.x / MuJoCo qpos / Kimodo CSV | **wxyz** |
| PhysX 내부 / Unitree CSV / GMR pkl / BeyondMimic CSV 입력 / PHC·ASAP·poselib | **xyzw** |
| **Isaac Lab 3.0** | **xyzw**(마이그레이션 가이드: "WXYZ to XYZW") |

- Isaac Sim 월드 좌표: 오른손 좌표계, Z-up, +X forward, m, rad(USD 속성은 도)
- AMASS: Z-up, +Y forward
- LAFAN1 BVH: Y-up, cm
- HumanML3D: Y-up
- OptiTrack: Y-up

### 1.5 권장 Canonical 저장 포맷 및 메타데이터 스키마

**디렉터리 구조 (3계층 + 메타)**

```
kh_motion/
  raw/<session>/                     # 변경 불가. sha256 기록
     *.tak | *.x2d *.mcp *.vsk | *.mvnx  (벤더 네이티브)
     *.c3d (SOMA 라벨링본), *.fbx/*.bvh (벤더 export), video/
  human/smplx/<clip_id>.npz          # AMASS SMPL-X 키와 완전히 동일하게. 커스텀 키 금지
  objects/<clip_id>.npz              # obj_<id>_pos (N,3), obj_<id>_quat_wxyz (N,4), (선택) articulation state
  robot/<robot_id>/<retarget_ver>/<clip_id>.npz
  meta/<clip_id>.json                # sidecar(아래 스키마)
  meta/index.parquet                 # 검색용 평탄화 인덱스(BONES-SEED와 같은 패턴)
  usd/<clip_id>.usd                  # (선택) SMPL-X 메시 SkelAnimation, 시각화용
```

- **human 정본 npz**
  - 키: `trans`(N,3, m), `root_orient`(N,3), `pose_body`(N,63), `pose_hand`(N,90), `pose_jaw`(N,3), `pose_eye`(N,6), `poses`(N,165), `betas`(16), `num_betas`, `gender`, `surface_model_type="smplx"`, `mocap_frame_rate`, `mocap_time_length`
  - 원본 fps(예: 120)를 그대로 보관한다.
  - 이렇게 하면 GMR, ProtoMotions, PHC 계열, aitviewer, Kimodo가 어댑터 없이 읽는다.
- **robot npz**(한 파일에 모두 담는다)
  - 일반화 좌표: `fps`, `joint_names`(D,), `root_pos`(N,3), `root_quat`(N,4, wxyz), `dof_pos`(N,D)
  - Isaac Sim replay에서 기록한 최대 좌표(BeyondMimic 호환): `joint_pos`, `joint_vel`, `body_names`, `body_pos_w`, `body_quat_w`(wxyz), `body_lin_vel_w`, `body_ang_vel_w`
  - 조밀 라벨: `contact`(N,4: LF, RF, LH, RH, uint8), `support_state`(N, int8), 물체 pose
  - fps: 50 Hz(BeyondMimic, SONIC 기본)를 기준으로 하고, 30 Hz(GMR, GMT)는 필요할 때 export한다.
- **필요할 때 생성하는 export**
  - Unitree 스타일 CSV(xyzw): BeyondMimic, mjlab용
  - GMR/GMT pkl(xyzw)
  - Isaac Lab AMP npz(wxyz)
  - Isaac Lab 3.0용(xyzw)

**메타데이터 sidecar 스키마 제안 (v0.1)**

```json
{
  "schema_version": "0.1",
  "clip_id": "KH26_S03_T012_A017_c01",
  "timing": {"fps": 50, "fps_raw": 120, "num_frames": 1354, "duration_s": 27.08,
             "range_convention": "[start, end) at canonical fps"},
  "frames": {"world": "right-handed, Z-up, +X forward (Isaac Sim)", "human_frame": "AMASS Z-up",
             "units": {"length": "m", "angle": "rad"}, "quat_convention": "wxyz", "ground_height_m": 0.0},
  "capture": {"system": "optical|imu|hybrid|video|public", "vendor": "OptiTrack|Vicon|Xsens|...",
              "software": "Motive 3.x / Shogun Post / MVN Animate", "marker_set": "MoSh++ layout",
              "hand_capture": "Manus|markers|none", "video_views": 4, "session_id": "S03",
              "capture_date": "YYYY-MM-DD", "raw_files": [{"path": "raw/S03/T012.tak", "sha256": "..."}]},
  "actor": {"actor_id": "A017(가명)", "height_m": 1.68, "mass_kg": 63.0, "gender": "female", "handedness": "right",
            "smplx": {"gender": "neutral", "num_betas": 16, "model_version": "SMPL-X v1.1"},
            "consent": {"public_release": true, "video_release": false, "consent_ref": "CF-2026-017"}},
  "task": {"task_id": "T012", "name_ko": "식탁 위 컵을 싱크대로 옮기기", "name_en": "move cup from table to sink",
           "difficulty": 2, "success": true, "failure_reason": null, "instruction_text": "..."},
  "segments": [
    {"seg_id": 1, "subtask": "locomotion",      "start_frame": 0,   "end_frame": 210},
    {"seg_id": 2, "subtask": "perception",      "start_frame": 150, "end_frame": 260},
    {"seg_id": 3, "subtask": "approach",        "start_frame": 210, "end_frame": 330},
    {"seg_id": 4, "subtask": "pre_manip_pose",  "start_frame": 330, "end_frame": 380},
    {"seg_id": 5, "subtask": "contact",         "start_frame": 380, "end_frame": 395},
    {"seg_id": 6, "subtask": "grasp",           "start_frame": 395, "end_frame": 430},
    {"seg_id": 7, "subtask": "carry",           "start_frame": 430, "end_frame": 900},
    {"seg_id": 8, "subtask": "place",           "start_frame": 900, "end_frame": 980},
    {"seg_id": 9, "subtask": "verify",          "start_frame": 980, "end_frame": 1354}
  ],
  "contacts": {"method": "mvnx_footContacts|force_plate|vel<0.15m/s&h<0.1m|manual",
               "effectors": ["left_foot", "right_foot", "left_hand", "right_hand"],
               "intervals": {"right_hand": [[380, 980]]}, "dense_ref": "robot npz: contact"},
  "support": {"enum": ["double", "left", "right", "flight", "kneel", "sit", "other"],
              "dense_ref": "robot npz: support_state"},
  "objects": [{"object_id": "cup_01", "category": "cup", "mesh_uri": "assets/cup_01.usd", "mass_kg": 0.3,
               "articulated": false, "pose_ref": "objects/<clip_id>.npz#cup_01", "source": "optical rigid body",
               "state_events": [{"frame": 395, "state": "grasped"}, {"frame": 980, "state": "placed_in_sink"}]}],
  "provenance": {"source_dataset": "own|CMU|CORE4D|AMASS/<subset>|...", "source_clip": null,
                 "fitting": {"tool": "SOMA+MoSh++", "version": "git sha", "marker_rmse_mm": 7.2}},
  "license": {"tag": "internal|CC-BY-4.0|CMU-mocap|CC-BY-NC-4.0|AMASS-NC|...", "url": "...",
              "commercial_ok": true, "redistribution_ok": true, "public_release_flag": true},
  "quality": {"marker_gap_ratio": 0.01, "foot_skate_m": 0.02, "penetration_max_m": 0.01, "flags": []},
  "retarget": {"robot_id": "lg_h30", "robot_model": {"file": "lg_h30.urdf", "sha256": "..."},
               "retargeter": "GMR", "retarget_version": "gmr@<sha>+cfg@<sha>", "height_scale": 0.97,
               "hand_retarget": "dex-retargeting position", "ik_err_mean_m": 0.03, "joint_limit_violations": 0},
  "validation": {"isaac_sim_version": "5.1.0", "isaac_lab_version": "2.3.2", "mode": "kinematic|pd_fixed_root|policy",
                 "status": "not_run|passed|failed|needs_review", "valid_for_kpi": true,
                 "metrics": {"self_collision_frames": 0, "max_joint_vel_rad_s": 9.1, "foot_penetration_max_m": 0.005},
                 "validated_at": "ISO8601", "validator": "replay_check.py@<sha>"}
}
```

운영 규칙:

- `segments`는 서브태스크 체인(이동, 인식, 접근, 조작 가능 자세 확보, 접촉 형성, 파지, 운반, 배치, 완료 확인)의 고정 enum을 쓴다. 겹침(예: 이동 중 인식)을 허용한다.
- 조밀 per-frame 배열은 npz에, 구간 정보는 JSON에 둔다. 프레임 범위는 canonical fps 기준이며 끝 포함 여부를 명시한다.
- `public_release_flag`는 사람이 직접 체크하지 않는다. `provenance`, `license`, `actor.consent`에서 **자동 계산**한다.
- KPI 집계(60 h 누적, 5 h 공개, 5 h 유효)는 `index.parquet`에서 바로 뽑는다(`valid_for_kpi`, `public_release_flag`, `duration_s` 합계).

### 1.6 포맷과 바디모델 라이선스 메모

- **SMPL-X 모델**(smpl-x.is.tue.mpg.de/modellicense.html), **SMPL**, **MoSh++**, **SOMA**, **smplx 코드**는 모두 MPI **비상업 과학 연구용**이다. 상업 목적의 신경망 학습도 금지된다.
- 상업 라이선스는 Meshcapade 또는 MPI(ps-license@tue.mpg.de)에 문의한다.
- SMPL-X 파라미터로 만든 로봇 궤적(파생물)에 대한 적용 범위는 명시되어 있지 않다. 법무 검토가 필요하다.
- **SMPL-X 비의존 경로**: 원본 스켈레톤(BVH, C3D, MVNX)에서 GMR로 로봇에 직접 리타겟하는 경로를 병행해 두면 리스크를 줄일 수 있다.

---

## 2. 공개 MoCap / 인간 모션 데이터셋

### 2.1 계획서 명시 및 주요 데이터셋

| 데이터셋 | 연도 | 규모 | 캡처 | 바디모델/포맷 | 손 | 물체 | 가정 관련성 | 라이선스 | 상업 | 재배포(파생 포함) | 링크 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **AMASS** | ICCV'19 (SMPL-X판 2022, 최종 업데이트 2024-11) | 40 h+ (논문 2,488분, 346명, 11,451 모션. 이후 추가분 포함 60 h+로 통용 [미확인]) | 15개 광학 마커 DB를 MoSh++로 통합 | SMPL-H(+DMPL), SMPL-X npz | △(MoSh 손, 품질 제한) | X | 하~중(CMU, KIT 일부 일상 동작) | MPI 비상업 연구 라이선스 + 하위 DB 조건 | X | X | amass.is.tue.mpg.de |
| **CMU Mocap** | 2000년대 | 2,605 trials, 피험자 #1~144(AMASS 내 약 9.3 h) | Vicon 12대, 120 Hz, 41 마커 | ASF/AMC, C3D, (cgspeed BVH) | 대부분 X | X(pose 없음) | 중: #13~15 일상, #26 들기, #62 의자 옮기기·정리, #86 청소, #137 머그, **#143 공구함·박스·빨래바구니 들고 걷기**, #144 reach | 자체 약관: 모든 용도 무료, 상용 제품에 포함 가능, 복제·수정·재배포 가능, **데이터 자체 재판매 금지** | **O** | **O**(판매 금지) | mocap.cs.cmu.edu |
| **LAFAN1** | SIGGRAPH'20 | 4.6 h, 77 seq, 30 fps, 5명 | 광학(시스템 [미확인]) | BVH | X | X | 하(보행, 장애물, 낙상, 기어가기) | **CC BY-NC-ND 4.0** | X | X(ND: 리타겟본 공유 불가) | github.com/ubisoft/ubisoft-laforge-animation-dataset |
| **HumanML3D** | CVPR'22 | 28.59 h, 14,616 모션, 44,970 텍스트, 20 fps | AMASS + HumanAct12 | 22관절 263-D 특징 + 텍스트 | X | X | 중(텍스트로 줍기, 앉기, 들고 걷기) | 코드 MIT. 모션은 AMASS 약관(직접 배포 불가, 재생성 스크립트 제공) | X | X | github.com/EricGuo5513/HumanML3D |
| **Motion-X / Motion-X++** | NeurIPS'23 / 2025 | 144.2 h, 81.1K seq / 180.9 h, 120.5K seq, 30 fps | 마커 mocap 일부 + 단안 영상 SMPL-X 추정 다수 | SMPL-X 322-D npy + 전신/프레임 텍스트 | O | X | 중(광범위 일상, 노이즈 있음) | 비상업(repo: NC 연구 라이선스, 페이지·논문: CC BY-NC-SA) + 하위 DB 조건 | X | NC만 | github.com/IDEA-Research/Motion-X |
| **BEAT2** | CVPR'24 | 60 h, 25명, 1,762 seq | Vicon를 SMPL-X로 피팅, 얼굴은 ARKit→FLAME | SMPL-X+FLAME npz, 30 fps | O | X | 없음(대화 제스처) | **상충**(HF 태그 apache-2.0, BEAT 페이지 "Non-commercial") | ? | ? | huggingface.co/datasets/H-Liu1997/BEAT2 |
| **GRAB** | ECCV'20 | 1,334 seq, 1.62M frames@120 fps(약 3.8 h), 10명, 51 물체 | Vicon 54대, 99 마커 | SMPL-X+MANO npz, 물체 pose와 mesh, 정점 접촉 | O | O(강체) | 중(테이블 위 파지·건네기, 이동 없음) | MPI NC | X | X | grab.is.tue.mpg.de |
| **ARCTIC** | CVPR'23 | 339 seq, 10명, 관절 물체 11종, 2.1M 이미지 | Vicon 54대 + RGB 9뷰 | SMPL-X+MANO, 물체 pose와 관절각, 접촉 | O(양손) | O(관절물체: 전자레인지, 노트북 등) | 중(가전 개폐, 이동 없음) | MPI NC | X | X | arctic.is.tue.mpg.de |
| **OMOMO** | SIGGRAPH Asia'23 | 약 10 h, 17명, 대형 물체 15종, 120 fps | Vicon 12대(Shogun) | SMPL-X, 물체 6DoF + mesh | X(손가락 부정확) | O | **상**: 의자·테이블·박스 운반, 청소기·밀대, 캐리어, 스탠드 | 데이터 라이선스 **명시 없음**(코드 MIT) | ? | ?(저자 서면 허락 필요) | github.com/lijiaman/omomo_release |
| **BEHAVE** | CVPR'22 | 321 seq, 8명, 20 물체, 5개 장소, 30 fps | Azure Kinect 4대(마커리스) | SMPL+H, 물체 pose + 스캔, 접촉 | △(저품질) | O | 중~상(박스·의자·테이블 들기, 운반, 밀기) | MPI-INF NC | X | X | virtualhumans.mpi-inf.mpg.de/behave |
| **InterCap** | GCPR'22 / IJCV'24 | 223 seq, 67,357 멀티뷰 프레임(약 37분 [미확인]), 10명, 10 물체 | Azure Kinect 6대 | SMPL-X, 물체 6DoF + mesh, 접촉 | O(추정) | O | 중(캐리어, 의자, 컵) | MPI NC | X | X | intercap.is.tue.mpg.de |
| **ParaHome** | CVPR'25 | 8.1 h, 207 seq, 38명, 22 물체, body 60 Hz | RGB 70대 + Xsens 수트 + Manus 장갑 | 관절 pkl + SMPL-X seq(2025-01), 물체 6DoF와 관절 상태, 텍스트 구간, 접촉(2025-07) | O | **O(관절 가구: 싱크, 냉장고, 세탁기, 가스레인지, 서랍)** | **상**(실제 주방·세탁, 다단계. 이동은 한 방 안) | **CC BY-NC-SA 4.0** | X | NC-SA로만 | github.com/snuvclab/ParaHome |
| **TRUMANS** | CVPR'24 | 15 h+, 약 1.6M frames@30 Hz, 실내 씬 100개, 7명 | Vicon + Shogun(실제 씬을 가상으로 복제) | SMPL-X npy, 물체 pose(20종, 관절 8종 URDF), 씬 mesh/occupancy, 액션 라벨·텍스트 구간 | O | O | **상**(거실·침실·주방·식당, 앉기·눕기·개폐) | 구글폼 약관: 비상업 연구·교육 | X | 언급 없음(불가로 간주) | jnnan.github.io/trumans |
| **CIRCLE** | CVPR'23 | 10 h, 5명, 9 씬, 7,000+ seq | 광학 마커 + VR(가상 아파트) | SMPL-X npz, BVH | X | X(가상) | 중(가구 사이, 테이블 아래 등 복잡 환경 reach) | **CC BY-NC 4.0**(코드 MIT) | X | NC로 가능 | tml.stanford.edu/circle_dataset |
| **HUMOTO** | ICCV'25 | 735 seq, 2.2 h, 30 fps, 63 물체(관절 부위 72개) | Rokoko IMU 수트·장갑 + Kinect, 아티스트 클린업 | Mixamo 호환 리그(FBX 추정 [미확인]), 물체 mesh, 3단계 텍스트 스크립트 | O | O | **상**(요리, 정리, 수납, 배치. 다단계) | Adobe Research License v1.1(비상업 연구용 재배포 가능). **상업 라이선스 별도 협의 가능**(christies@adobe.com) | X(협의 가능) | NC 연구만 | jiaxin-lu.github.io/humoto, github.com/adobe-research/humoto |
| **Nymeria (+NymeriaPlus 2026)** | ECCV'24 / 2026-03 | 300 h, 264명, 50개 장소(임대 주택 47채), 1,200 seq, 언어 230 h | **Xsens MVN Link** + Aria 안경·손목밴드 + 관찰자 Aria | Momentum 바디. NymeriaPlus는 MHR, SMPL 추가 | △(손목만 [미확인]) | △(NymeriaPlus 3D 박스·재구성, 조작 수준 아님) | 중~상(실제 집 일상 이동, 시선) | **CC BY-NC 4.0** | X | NC로 가능 | projectaria.com/datasets/nymeria |
| **EgoBody** | ECCV'22 | 125 seq, 36명, 15 씬 | Azure Kinect 3~5대 + HoloLens2 | SMPL-X pkl, 씬 mesh, 시선 | O(마커리스) | X | 하(사회적 상호작용) | CC BY-NC-SA + **ETH 추가 약관(재배포 금지)** | X | X | egobody.ethz.ch |
| **HOI-M3** | CVPR'24 | 199 seq, 20 h+, 90 물체, 다인원 | Z CAM 42대(마커리스) + 물체 IMU | SMPL-X npz(toolbox), 물체 6DoF + mesh | O(마커리스) | O | 중~상(침실, 거실, 식당. 주방 없음) | 데이터 라이선스 **명시 없음**(툴박스 Apache-2.0) | ? | ? | juzezhang.github.io/HOIM3_ProjectPage |
| **CORE4D** | CVPR'25 | Real 약 1K seq(31명, 38 물체) + Synthetic 약 10K, 15 fps | Noitom 하이브리드 + 장갑 + Kinect 4대 | SMPL-X, 물체 6DoF + mesh, 협업 모드 라벨 | O | O(박스, 판, 통, 의자, 책상) | 중~상(가구·박스 재배치, 장애물. 2인 협업 위주, 단독 이동 모드 있음) | **CC BY 4.0**(HF 메타데이터는 MIT) | **O** | **O**(출처 표시) | core4d.github.io |

### 2.2 2025~2026 신규 및 휴머노이드용 리타겟 데이터

| 데이터셋 | 시기 | 규모 / 내용 | 포맷 | 라이선스 / 리스크 | 링크 |
|---|---|---|---|---|---|
| **ACE-Data-0** | 2026-07 (arXiv 2607.28625) | 150 h, 75K 에피소드, 200 태스크, 50명 이상. 200 m² 아파트(룸 스케일)와 데스크(테이블 스케일). OptiTrack 22대, Manus 장갑, 촉각 장갑, ego/exo 영상. **goal과 sub-goal 시퀀스**, chained HOI | 41관절 스켈레톤 + SMPL-X, 물체 6DoF@60 Hz, LeRobot parquet | Research License: 비상업, 재배포 금지, 개인 단위·양도 불가. **데이터 파일 아직 미공개**(HF 카드 기준) | ace-data-engine.github.io/ACE-Data-0 |
| **BONES-SEED** (Bones Studio, NVIDIA SOMA) | 2026-03 (GTC) | 142,220 모션(원본 71K + 미러), **약 288 h**, 120 fps, 522명, Vicon. 카테고리: Locomotion, Interactions(14,643), 일상 활동 등. 텍스트 최대 6개와 시간 구간 라벨(NVIDIA, CC BY 4.0) | SOMA BVH(uniform/proportional), **Unitree G1 CSV** | BONES-SEED License: **학술(비상업, 공개 연구) 또는 연매출 100만 달러 미만 스타트업만 허용**. 그 외에는 상업 라이선스 필요. 원본과 G1 CSV 모두 재배포 금지. 제어 정책 학습은 허용 → **NC AI는 적용 대상이 아닐 가능성이 높다** | huggingface.co/datasets/bones-studio/seed, bones.studio/info/seed-license |
| **HiPHI** (Noitom / ModalityNet) | 2026-08 (CoRL'26) | 원본 308.7 h(미러 포함 617.5 h), HOI 245.7 h, 90 Hz, 132명, 물체 40개(0.45~6.25 kg). FrameNet 라벨(walk, kneel, lift, carry, push, pull) | 55관절 BVH(Y-up, cm, ZXY), 물체 CSV + OBJ. SMPL-X 아님 | ModalityNet Open Research License: 비상업. 상업 라이선스는 info@modalitynet.com | huggingface.co/datasets/noitomrobotics/HiPHI |
| **Embody 3D** (Meta) | 2025-10 | 500 h, 439명, 30 fps. Day-in-the-Life(아파트 세트) 46 h | SMPL-X npy + 텍스트 | XRCIA 비상업, 재배포 금지 | github.com/facebookresearch/embody-3d |
| **PHUMA** | 2025-10 (CoRL'26) | 73 h, 물리 보정된 G1/H1-2 모션(AMASS, Motion-X, Humanoid-X 기반) | npy(`root_trans`, `root_ori` xyzw, `dof_pos`, `fps`) | HF 태그 Apache-2.0이지만 **상위 소스가 NC**다. LAFAN1과 LocoMuJoCo 유래분은 라이선스 문제로 제외됨 → 상업·공개 리스크 높음. PhySINK 리타겟 코드(Apache-2.0)는 재사용 가능 | huggingface.co/datasets/DAVIAN-Robotics/PHUMA |
| **OmniRetarget dataset** (Amazon FAR) | 2025-09 | G1 4 h: 로봇-물체 3 h(OMOMO 기반), 지형 0.5 h, 물체+지형 0.5 h | npz(`fps`, `qpos` 36 + 물체 7) | MIT. 단 **OMOMO 원천의 데이터 라이선스가 불명**하다. LAFAN1 리타겟본은 미공개 | huggingface.co/datasets/omniretarget/OmniRetarget_Dataset |
| **AMASS→G1 리타겟** (fleaven, ember-lab-berkeley) | 2025 | G1 [-1,36] 배열 6.95 GB, Isaac Lab AMP 로더 형식 11.9 GB | npy, npz | HF 태그 CC BY 4.0이지만 **README가 AMASS 약관을 따른다고 명시** → 비상업, 재배포 불가 | huggingface.co/datasets/ember-lab-berkeley/AMASS_Retargeted_for_G1 |
| **Unitree LAFAN1 retarget** | 2024~ | G1, H1, H1-2 CSV, 30 fps | CSV(xyzw) | **CC BY-NC-ND 4.0** | huggingface.co/datasets/lvhaidong/LAFAN1_Retargeting_Dataset |
| **MMHOI** (MERL) | WACV'26 (2025-11) | 약 600K frames@30 fps(약 5.6 h [미확인]), 13명, 22 물체, 12 시나리오(식사, 협업) | SMPL-X(+SMPL-H), 물체 6DoF | **CC BY-SA 4.0**: 상업 O, 파생물도 CC BY-SA. Kinect 마커리스라 품질은 낮다 | zenodo.org/records/17711786 |
| **100STYLE** | 2022 | 100가지 보행 스타일, 4M+ 프레임@60 fps(약 18.5 h 추정) | BVH(Xsens) | **CC BY 4.0**: 상업 O, 재배포 O | ianxmason.com/100style |
| LINGO | SIGGRAPH Asia'24 | 16 h, 120 실내 씬, 언어 구간, 손 접촉 프레임 | SMPL-X(손가락 없음) | 데이터 라이선스 명시 없음 | github.com/mileret/lingo-release |
| IMHD | CVPR'24 | 295 seq, 고동적 HOI | SMPL-H | CC BY-NC-SA 4.0. 가정 관련성 낮음 | github.com/AfterJourney00/IMHD-Dataset |
| MotionMillion / Humanoid-X | 2025 | 2,000 h+ / 대규모 영상 기반 | SMPL / 로봇 | NC-SA + 커뮤니티 라이선스 / 일부만 공개. 물체 없음 | HF InternRobotics/MotionMillion, USC-GVL/Humanoid-X |
| 손 중심: OakInk2, HOT3D, GigaHands, TACO | 2024~25 | 파지·도구 사용(전신 이동 없음) | MANO 등 | OakInk2 HF CC BY-SA(GitHub 미기재), HOT3D 분할 라이선스(손 주석은 NC-SA), GigaHands 미공개, TACO [미확인] | 접촉·파지 단계 손 prior용 |
| 발표만, 미공개: ω-HOME, OmniContact | 2026 | 가정 휴머노이드 40 h+(11 태스크) / 박스 운반 HOI | – | 공개 링크·라이선스 없음 | arXiv 2608.06375, 2606.26201 |
| 국내: AIHub "대화·발표 동작 모션캡처" | 2022 | 1,352건, BVH/FBX/QTM | BVH, FBX | 내국인만 신청 가능, AI 학습 목적 한정, 상업 이용은 구축기관과 협의. 가정 조작 관련성 낮음 | aihub.or.kr(dataSetSn=71419) |

### 2.3 서브태스크별 적합 데이터셋

| 서브태스크 | 1순위 (내부 R&D) | 공개 가능 후보 | 비고 |
|---|---|---|---|
| 이동 | AMASS, Nymeria, BONES-SEED, PHUMA, LAFAN1(내부만) | **CMU 원본, 100STYLE** | 가장 풍부하다. 자체 촬영 비중을 낮춰도 된다 |
| 인식(탐색, 시선) | Nymeria(시선, 실제 집), EgoBody(시선), ACE-Data-0 | – | MoCap에 "찾기" 행동 라벨이 드물다. **자체 촬영에서 머리·시선 방향 라벨을 확보**해야 한다 |
| 접근 | OMOMO, TRUMANS, CIRCLE, ParaHome | CMU #143, CORE4D | 목표 물체까지 감속, 정렬, 방향 전환 |
| 조작 가능 자세 확보(웅크림, 숙임, 리치) | CIRCLE(복잡 환경 리치), TRUMANS, GRAB, HiPHI(kneel/lift) | CMU #144, CORE4D | 30 DoF 로봇(허리 2 DoF)의 가동범위를 고려해 자체 촬영 시 자세를 조정한다 |
| 접촉 형성 / 파지 | GRAB, ARCTIC, ParaHome, HUMOTO, InterCap | MMHOI(저품질) | 손가락은 MANO가 있는 데이터만 해당. 15 DoF 4지 손 리타겟 필요 |
| 운반 | **OMOMO**, BEHAVE, HiPHI, OmniRetarget(G1) | **CORE4D**, CMU #143 | 무게 있는 물체를 들고 걷는 자세와 보폭 |
| 배치 | OMOMO, ParaHome, HUMOTO, TRUMANS | CORE4D | 놓기 직전 감속, 정렬 |
| 완료 확인 | ParaHome(텍스트 구간), HUMOTO(스크립트), ACE-Data-0(sub-goal), TRUMANS(액션 구간) | – | 명시적 "확인" 동작 라벨은 사실상 없다 → **자체 촬영과 라벨 정의가 필요** |

### 2.4 라이선스 리스크 노트 (공개 5 h 지정용)

| 등급 | 데이터 | 공개 5 h 사용 |
|---|---|---|
| **녹색**(상업·재배포 가능) | **자체 촬영분**(액터 공개 동의 확보), **CMU 원본**(재판매 금지), **CORE4D**(CC BY 4.0), **100STYLE**(CC BY 4.0), **MMHOI**(CC BY-SA 4.0, 파생물도 SA) | 가능. 출처 표시와 SA 조건을 준수한다 |
| **황색**(비상업 조건으로 재배포 가능) | CIRCLE, Nymeria(CC BY-NC), ParaHome(CC BY-NC-SA), HUMOTO(Adobe Research, NC), Motion-X(NC), IMHD | "비상업 연구 전용" 하위셋으로만 공개할 수 있다. 기업 과제 성과물로 공개 시 상업성 해석 리스크가 있다 → 법무 판단 필요 |
| **적색**(재배포 금지 또는 불명) | AMASS와 모든 AMASS 파생물(HumanML3D, AMASS→G1, PHUMA 일부), **LAFAN1(ND)**, GRAB, ARCTIC, InterCap, BEHAVE, EgoBody, TRUMANS, Embody3D, ACE-Data-0, **BONES-SEED**, HiPHI, OMOMO·HOI-M3·LINGO(라이선스 미기재 = 권리 유보), BEAT2(상충) | 공개 불가. 내부 R&D와 60 h 누적에만 사용(약관 범위 내) |

KPI 관점 참고:

- 가정 HOI 계열 공개 데이터만으로도 OMOMO(10 h), ParaHome(8.1 h), TRUMANS(15 h+), HUMOTO(2.2 h), CIRCLE(10 h) 등 수십 시간이 확보된다.
- 이동 계열(AMASS 40 h+)을 더하면 **60 h 누적(내부)**은 공개 데이터로 상당 부분 충당할 수 있다.
- 다만 "유효 5 h"(Isaac Sim 재생 검증)와 "공개 5 h"는 자체 촬영과 녹색 등급 데이터로 별도 관리한다.

주의:

- **"AMASS 안의 CMU"는 적색이다.** CMU를 공개용으로 쓰려면 mocap.cs.cmu.edu의 원본 ASF/AMC나 C3D에서 직접 처리한다. 자체 MoSh++ 피팅은 MoSh++ 자체가 NC라는 점에 유의한다.
- **SMPL-X 의존성**: 공개본을 SMPL-X 파라미터로 배포하면 사용자에게 SMPL-X 모델 라이선스가 필요하다. 공개본은 **로봇 관절공간 궤적과 원본 스켈레톤(BVH/C3D)**을 기본으로 하고, SMPL-X는 선택 제공을 권장한다.
- **기업 참여 리스크**: NC AI 참여와 LG 제품 연계는 다수 NC 라이선스상 "상업 목적"으로 해석될 수 있다. 특히 MPI 계열(AMASS, SMPL-X, GRAB 등)은 **상업 목적의 신경망 학습까지 금지**한다. 1차년도 내부 사용 범위도 법무 확인을 권장한다.
- **자체 촬영의 권리 확보**
  - 액터 동의서에 모션 데이터 공개 재배포, 영상 공개 여부, 체형(betas)·키 공개를 명시한다.
  - 개인정보보호법상 영상 얼굴은 비식별 처리한다.
  - 공개 라이선스는 CC BY 4.0 계열을 권장한다.

---

## 3. 액터용 레퍼런스 영상

공통 원칙:

- 액터 레퍼런스로 내부 상영하는 것은 대부분 데이터셋 라이선스가 **명시적으로 다루지 않는 회색지대**다.
- 외부 액터가 "제3자"에 해당하는지, 과제가 "상업"에 해당하는지를 먼저 판단한다.
- 가장 안전한 경로는 다음 순서다.
  1. 자체 레퍼런스 영상 촬영
  2. CMU-MMAC("free to use for any purpose")
  3. 공식 YouTube 데모 스트리밍(다운로드·재업로드 금지)

### 3.1 데이터셋 영상

평점은 단계 순서(이동/인식/접근/자세/접촉·파지/운반/배치/확인)를 따른다. H=높음, M=중간, L=낮음.

| 소스 | 영상 종류 | 규모 | 접근 | 라이선스 / 이용 조건 | 액터 레퍼런스 적합도 | 링크 |
|---|---|---|---|---|---|---|
| **Ego-Exo4D** | ego(Aria, 시선)와 exo GoPro 4~5대 동기화(전신이 보임). 비연출 과업 | 1,286 h. **Cooking 564 h**(678 테이크) | 라이선스 서명, 약 48 h 승인, AWS 14일 | 문서상 "research and commercial use"를 다루고 재배포는 제한. 전문은 [미확인] | M/H/H/H/H/M/H/H. **자세(exo)와 시선(ego)을 함께 보는 최적 소스** | ego-exo4d-data.org |
| **Ego4D** | 1인칭 전용, 비연출 일상 | 3,670 h, 923명 | 라이선스 서명, 약 48 h | 목적 한정(연구, 객체·행동 인식 기술 개발, **상업 제품 개발 포함**). **제3자 접근 제공 금지** → 액터 상영은 회색지대 | L/M/L/L/H/M/M/M | ego4d-data.org |
| **EPIC-KITCHENS-100** | 머리 착용 1인칭, 비연출 주방 | 100 h, 45개 주방 | 공개 다운로드 | **CC BY-NC 4.0**(상업 라이선스는 문의) | L/M-H/L/L/H/M/H/M | epic-kitchens.github.io |
| **HD-EPIC** (2025) | Aria, 자기 집 주방, 다일 녹화, 시선 | 41 h, 주방 9곳, 59.4K 액션, 레시피 단계 | 공개 | CC BY-NC 4.0 | L/H/L/L/H/M/H/M-H. 탐색과 확인 시선 | hd-epic.github.io |
| **Charades / Charades-Ego** | 3인칭(Ego는 1·3인칭 쌍), 스크립트, 자기 집 촬영 | 9,848편, 약 30초 / 68.8 h | 공식 페이지가 allenai.org 홈으로 리다이렉트 [미확인] | 비상업·학술 [미확인] | M/L/M/M/L/M/M/L. 전신·집이지만 아마추어 품질 | (공식 랜딩 [미확인]) |
| **Assembly101** | 정적 8뷰 + ego 4뷰, 책상 조립·분해, 실수와 수정 | 4,321편 | HF(2026-05부터 이전, Google Drive 단계적 종료) | CC BY-NC 4.0 | 접촉·파지 H, 확인(실수 검출) M. 그 외 L | assembly-101.github.io |
| **HOI4D** | 1인칭 RGB-D 손-물체(관절 물체 포함) | 4,000+ seq, 610개 방 | 공개 | CC BY-NC 4.0 | 접촉·파지 H. 그 외 L | hoi4d.github.io |
| **ParaHome** | RGB 70대 촬영. 원본 RGB 공개 여부는 [미확인], 렌더·데모 클립 있음 | 8.1 h | Google Drive | CC BY-NC-SA 4.0 | 자세 H(렌더), 이동·접근 M | jlogkim.github.io/parahome |
| **Nymeria** | Aria 1인칭 + **관찰자 3인칭** + Xsens 전신 | 300 h, 실제 집 47채 | 이메일 신청 | CC BY-NC 4.0 | H/H/H/H/M/H/M/M. **여러 방을 오가는 실제 집 이동의 최적 소스** | projectaria.com/datasets/nymeria |
| **Something-Something v2** | 손 클로즈업, 템플릿 행동 | 220,847 클립 | Qualcomm 로그인 | Research Use 약관 [미확인] | 접촉·파지 M. 그 외 L | qualcomm.com(SSv2) |
| **Home Action Genome (HOMAGE)** | ego 1 + 3인칭 2~5 동기화, 활동 수준 지시만(비스크립트) | 1,752 seq, 약 25~30 h, 주방·욕실·침실·거실·세탁실 | 웹폼 신청 | 파나소닉 소유, 비상업·학술, 제3자 제공 금지 | M/M/H/H/M/H/H/M. 빨래, 침구 정리 등 | homeactiongenome.org |
| **Toyota Smarthome** | Kinect 7대, 아파트, 노인 18명 자연 행동 | 16,115 클립 / 536편 비트림(평균 21분) | 업무 이메일로 신청 | 학술 연구 전용 | H/M/H/M/L/M/M/L. 자연스러운 방 간 이동 | project.inria.fr/toyotasmarthome |
| **ETRI-Activity3D (+LivingLab)** | Kinect v2 8대, **로봇 높이(70 cm, 120 cm) 시점**, 31평 아파트 테스트베드 / 독거노인 50가구 | 112,620 샘플, 55개 일상 행동(청소기, 이불 개기, 빨래 널기) | ETRI 담당자 연락 | 미기재 [미확인]. ETRI 문의 필요 | M/L/M/H/L/M/M/L. **국내 가정, 바닥 높이 작업 자세** | ai4robot.github.io/etri-activity3d |
| NTU RGB+D 60/120 | Kinect 실험실, 단일 행동 | 114,480 샘플 | 계약서 서명 | 비상업, 재배포 금지 | 줍기 자세 정도(L~M) | rose1.ntu.edu.sg |
| AIHub 일상생활 영상(648) | GoPro 1·3인칭, 한국인 약 200명, 청소·빨래·설거지 | 약 7,000 h | 내국인만, 승인 필요 | **AI 학습 목적 한정**, 승인 외 열람·제공 금지 → 액터 상영은 NIA 승인 필요 | M(문화적 적합) | aihub.or.kr(dataSetSn=648) |
| **CMU-MMAC (Kitchen)** | 3인칭 다중 카메라 + 웨어러블 + Vicon + IMU, 요리 5종 | 43명 내외 | 공개 | **"free to use for any purpose"**(인용·감사 표기) | 자세·접근 M~H. **라이선스가 가장 깨끗하다** | kitchen.cs.cmu.edu |
| Breakfast Actions | 3~5 카메라, 저해상도, 18개 주방 | 약 77 h | 공개 | CC BY 4.0과 "All rights reserved" 표기가 상충 [미확인] | L~M | serre.lab.brown.edu |
| EgoLife | 공유 주택 7일, ego + GoPro 15대 | – | HF | HF 카드 MIT. exo 공개 여부 [미확인] | 일상 동선 M | egolife-ai.github.io |

### 3.2 휴머노이드 기업 데모 영상 (공식 채널)

- 이용 조건은 공통이다. **YouTube 표준 라이선스**에 따라 스트리밍 시청과 링크·임베드 공유만 가능하다. 다운로드, 재업로드, 편집 재배포는 금지된다.
- 재업로드 채널(RoboFrontier, Daily Mail 등)이 아니라 공식 채널만 사용한다.
- 로봇 데모는 **인간 모션이 아니다.** "로봇이 실현 가능한 템포와 스타일"의 참고로만 쓴다(넓은 스탠스, 느린 동작, 엉덩이·발로 서랍과 문 조작).

| 회사 | 영상 | 내용 |
|---|---|---|
| Figure AI | "Introducing Helix 02" youtube.com/watch?v=lQsvTrRTBRs (2026-01) | 약 4분 완전 자율. 식기세척기 언로드·로드, 방 가로질러 찬장 정리, **엉덩이로 서랍 닫기, 발로 문 들기**. 61개 loco-manipulation 동작. 하위 제어기는 리타겟된 인간 모션 1,000 h+로 학습 |
| Figure AI | "Helix 02 Living Room Tidy" watch?v=CAdTjePDBfc (2026-03), "Bedroom Tidy" watch?v=8xEuFQz4E4A (2026-05, 내용 [미확인]), "Introducing Figure 03" watch?v=Eu5mYMavctM (2025-10) | 거실·침실 정리, 침대 정리. 뉴스: Helix 2.5 "30-Home Generalization"(2026-09), 빨래 개기, 식기세척기 |
| 1X | "NEO The Home Robot" watch?v=LTYMWadOW7c (2025-10) | 빨래, 식기세척기, 청소기, 책 정리, 문 열기(일부 원격조종) |
| 1X | "NEO is Starting to Learn on Its Own" watch?v=lS_z60kjVEk, "1X & NVIDIA" watch?v=i1SvmFWu834 | 도시락 싸기, 다림질, 미닫이문(내용 매칭 [미확인]) |
| Tesla Optimus | "Optimus - Gen 2" watch?v=cpraXaw7dyc (2023) | 가사 아님. 2025-05 가사 클립(쓰레기, 청소기, 커튼)은 X(트위터)에 게시, URL [미확인] |
| Unitree | "Real-Time Omni-Modal Interaction Driven Whole-Body Mobile Manipulation" watch?v=IiNbFPOUrz8 | G1이 바닥 쿠션 줍기, 침대 옷을 바구니로 옮기기, 서랍에서 약 찾기, 접시를 식기세척기에 넣기(내용 매칭 [미확인]) |
| Boston Dynamics Atlas | "Getting a Leg up with End-to-end Neural Networks" watch?v=HYwekersccY (2025-08, TRI LBM) | 산업 환경이지만 **넓은 스탠스 쪼그려 앉기, 뒤돌아 집기, 낮은 선반 당기기, 떨어뜨린 부품 회수**. 자세와 운반 참고에 최적 |
| Apptronik Apollo | "Gemini Robotics … with Apptronik" watch?v=ikZeU3wKVjM (Google DeepMind 채널) | 2026-07 Gemini Robotics 2 데모(물뿌리개 들고 이동 후 선반에 배치)의 공식 URL은 [미확인] |
| Agility Digit | "The Next Generation of Digit" watch?v=rnFZAB9ogEE | 물류 토트 운반 전용. 가정 데모 없음 |
| Physical Intelligence (휠형) | "π0.5" watch?v=Zn8yMaepzVk (2025-04) | 낯선 집에서 설거지, 침대 정리, 빨래 바구니, 얼룩 닦기 |
| Sunday Robotics (휠형) | "ACT-2 Preview: 3hrs of Memo Folding Laundry" watch?v=a2HZyURUE_o | 빨래 개기 장시간 |

### 3.3 서브태스크별 추천 레퍼런스 (상위 5)

| 단계 | 추천 |
|---|---|
| 이동 | Nymeria, Toyota Smarthome(비트림), Ego-Exo4D Cooking exo, HOMAGE, Figure Helix 02 |
| 인식(탐색·시선) | Ego-Exo4D(시선+exo), Nymeria(시선+관찰자), HD-EPIC, EPIC-KITCHENS-100, HOMAGE |
| 접근 | Ego-Exo4D exo, **ETRI-Activity3D**(로봇 높이 시점), HOMAGE, Toyota Smarthome, Nymeria |
| 조작 가능 자세 확보 | ETRI-Activity3D/LivingLab, Nymeria, Ego-Exo4D exo, CMU-MMAC, Atlas LBM 영상 |
| 접촉 → 파지 | HOI4D, Ego-Exo4D ego, EPIC-KITCHENS/HD-EPIC, ParaHome, Something-Something v2 |
| 운반 | Nymeria, HOMAGE(빨래), ETRI-Activity3D, CMU-MMAC, Figure Helix 02 / Atlas LBM |
| 배치 | Ego-Exo4D, EPIC-KITCHENS/HD-EPIC, HOMAGE, Figure Helix 식기세척기, CMU-MMAC |
| 완료 확인 | Ego-Exo4D(keystep, 전문가 코멘트, 시선), HD-EPIC(레시피 단계), Nymeria, Assembly101(실수 검출), EPIC-KITCHENS |

실무 권장:

- 태스크가 확정되면 **태스크당 3~5개 클립 링크와 타임스탬프로 "연기 가이드 시트"**를 만든다.
- 가이드 시트 구성: 서브태스크 경계, 시선 방향, 손 사용, 속도, 실패 연출 방법
- 라이선스가 애매한 데이터셋은 연구진(서명 주체)만 보고, 액터에게는 **자체 촬영 레퍼런스 영상**을 주는 2단계 방식을 권장한다.

---

## 4. 툴링: 리타겟과 Isaac Sim 재생·시각화

### 4.1 인간→휴머노이드 리타겟 도구

| 도구 | 라이선스 / 상태 | 입력 | 방식 | 로봇 추가 방법 | 손 / 물체 | 출력 / 시뮬레이터 |
|---|---|---|---|---|---|---|
| **GMR** (YanjieZe/GMR) | MIT. 2025-08 공개, 2026-01까지 활발(Xsens BVH, Fourier GR3 추가). ICRA 2026 | SMPL-X(AMASS, OMOMO), BVH(LAFAN1, Nokov, **Xsens**), **OptiTrack FBX**(오프라인·스트리밍), Xsens MVN 실시간, PICO, GVHMR(단안 영상) | **mink + MuJoCo 프레임별 differential IK**(2단계 match table, 관절·속도 한계), 키 기반 스케일링. CPU에서 35~70 FPS | MJCF(floating base) + `params.py` 등록 + IK JSON(`human_scale_table`, `ik_match_table1/2`, 회전 오프셋 wxyz). 발 바디 이름에 "foot"이 들어가야 한다 | 손가락 리타겟 없음(별도 패스). 물체·접촉 보존 X | pkl(xyzw), CSV 변환. MuJoCo 뷰어 |
| **PHC / SMPLSim** (ZhengyiLuo) | BSD-3-Clause-Clear / BSD-3 | AMASS SMPL | `fit_smpl_shape`(SMPL 형상을 로봇에 맞춤) → `fit_smpl_motion`(PyTorch 경사 최적화) | 로봇 YAML(`joint_matches`, `extend_config`, `smpl_pose_modifier`) | X / X | joblib pkl. Isaac Gym, Isaac Lab 평가 스크립트(2025-08) |
| **ProtoMotions** (NVlabs) | Apache-2.0. v3.0(2026-01), v3.1(2026-02), 최신 변경 2026-08 | AMASS SMPL/SMPL-X, PHUMA, BONES-SEED BVH/G1 CSV, Kimodo | v3: **PyRoki 궤적 최적화**(15초 클립, 발 접촉 비용). 이전 버전은 mink | MJCF + `robot_configs/<robot>.py` + `factory.py` 등록. 리타겟 스크립트는 G1, H1-2만 있어 복제가 필요 | X / 학습 시 씬 물체 지원 | `.motion` → `.pt` MotionLib. **Isaac Lab 3.0(Isaac Sim 6.0)**, Newton, Isaac Gym, MuJoCo |
| **HumanoidVerse / ASAP** (LeCAR-Lab) | MIT | AMASS SMPL+H | PHC 파생 | 로봇 XML + config | X | pkl. Isaac Gym, Isaac Sim 4.2(구버전) |
| **mink** | Apache-2.0, v1.3.0(2026-08) | – | MuJoCo 기반 differential IK 라이브러리(충돌 회피, 폐쇄 체인) | – | – | GMR, PBHC, MaskedMimic의 기반 |
| **PyRoki** | MIT(JAX, URDF 기반, LM 솔버) | – | 궤적 최적화, Humanoid/Hand Retargeting 예제, mimic joint 지원 | URDF | 손 예제 있음 | ProtoMotions v3, VideoMimic |
| **OmniRetarget / holosoma** (Amazon FAR) | Apache-2.0(holosoma). OmniRetarget 공식 코드인지는 [미확인] | OMOMO, LAFAN BVH, AMASS SMPL-X, 커스텀 (T,J,3) | **interaction mesh + Laplacian 변형**으로 **물체·지형 접촉 보존** | `ADD_ROBOT_TYPE_README.md`(404, [미확인]) | 물체 O | npz, 50 fps. Isaac Gym, Isaac Sim, MJWarp |
| **NVIDIA soma-retargeter** | Apache-2.0(베타) | SOMA BVH만 | Newton + Warp GPU IK | Robot Configurator. G1, H2, T1, AgiBot | X | CSV |
| **dex-retargeting** (손) | MIT, v0.5.0 | MANO/MediaPipe 21 키포인트 | `position`(오프라인 HOI), `vector`/`dexpilot`(텔레옵) | 손 URDF + YAML(Allegro 4지 16 DoF 템플릿이 가장 가깝다) | **손 전용** | Isaac Lab 2.3 텔레옵, IsaacTeleop에서 사용 |

### 4.2 트래킹 정책별 모션 입력

| 방법 | 기대 입력 | 시뮬레이터 | 코드 상태 |
|---|---|---|---|
| **GMT** (zixuan417) | GMR 키와 같은 pkl(`fps`, `root_pos`, `root_rot` xyzw, `dof_pos`) | MuJoCo sim2sim만 | 체크포인트와 sim2sim만 공개. **학습 코드 미공개**("data processing and retargeter code soon") |
| TWIST / TWIST2 | GMR pkl | Isaac Gym, MuJoCo | 공개(MIT) |
| **BeyondMimic** | Unitree CSV(xyzw) → npz(50 Hz) | **Isaac Lab 2.1.0 / Isaac Sim 4.5**(README 고정) | 공개(MIT), G1 |
| **SONIC** (GR00T-WholeBodyControl) | joblib pkl(MuJoCo 순서 dof) + 50 Hz CSV | Isaac Lab 2.3.x + MuJoCo | 공개(코드 Apache-2.0, 가중치 NVIDIA Open Model License). **새 로봇(H2, 31 DoF) 가이드 있음** |
| ProtoMotions v3 | `.pt` MotionLib | Isaac Lab 3.0 / Newton | 공개 |
| MimicKit | pkl(root + exp-map, DFS 순서). `gmr_to_mimickit` | Isaac Gym, Isaac Lab, Newton | 공개 |
| KungfuBot / PBHC | SMPL(GVHMR, AMASS) → mink/PHC 리타겟 | Isaac Gym | **CC BY-NC 4.0**(코드) |
| OpenTrack(Any2Track) | G1 npz, 50 Hz | MuJoCo JAX | Apache-2.0 |

### 4.3 Isaac Sim / Isaac Lab 버전 현황 (2026-10 기준)

| 버전 | 시기 | 비고 |
|---|---|---|
| Isaac Lab 2.1.0 / Isaac Sim 4.5 | 2025-04 | BeyondMimic 고정 버전 |
| Isaac Lab 2.2.0 / Isaac Sim 5.0 | 2025-08 | 4.5와 하위 호환 |
| Isaac Lab 2.3.0 / Isaac Sim 5.1 | 2025-10 | G1 loco-manipulation Mimic, dex-retargeting 수정 |
| **Isaac Lab 2.3.2** / Isaac Sim 5.1 | 2026-02 | **2.x 마지막 릴리스**. Isaac Sim 5.1 문서는 현재 "unsupported"로 표기 |
| Isaac Lab 3.0.0-beta / Isaac Sim 6.0 | 2026-03 | Newton 백엔드, 텔레옵은 Isaac Teleop로 이동, URDF/MJCF 임포터 재작성, **쿼터니언 xyzw로 변경** |
| **Isaac Lab 3.0.0-EA** / Isaac Sim 6.1 | 2026-09-16 | GA 목표 2026-10월 말 |
| Isaac Sim 6.2.0 | 2026-10 | Newton 1.6.1, MuJoCo 3.12 |

권장:

- **(A) 단기**: 1차년도 검증은 **Isaac Lab 2.3.2 + Isaac Sim 5.1**로 한다. BeyondMimic, SONIC 생태계와 호환되고 계획서의 5.x/2.x와도 맞는다.
- **(B) 중기**: Isaac Lab 3.0 GA가 나오면 이전을 계획한다(ProtoMotions v3 사용 시). URDF 임포터 API(`URDFImporter(URDFImporterConfig)`)와 쿼터니언 규약이 깨지는 변경이므로 **스택별로 conda 환경을 분리**한다.

### 4.4 Isaac Sim에서 MoCap 재생·시각화 방법

| 방식 | 내용 | 용도 |
|---|---|---|
| **A. 로봇 kinematic replay(권장)** | 매 프레임 `write_root_state_to_sim` + `write_joint_state_to_sim`를 쓰고 `sim.render()`(물리 스텝 없음). BeyondMimic `csv_to_npz.py`/`replay_npz.py` 패턴을 LG `ArticulationCfg`와 관절 리스트로 포크하고, W&B 대신 로컬 파일을 쓴다 | 관절 한계, 자기충돌, 발 관통, 물체 위치 정합 확인. body state npz 생성. **"유효 데이터 5 h" 판정의 1차 기준** |
| A2. PD 추종 replay | 루트를 고정하거나 하네스로 잡고 PD로 관절을 추종 | 토크와 추종 가능성 확인(자유 부유 재생은 정책이 필요) |
| **B. 사람 메시 UsdSkel 오버레이** | `smplx` forward 결과로 `pxr.UsdSkel` Skeleton, SkelAnimation, 스킨 메시를 직접 작성(가장 통제 가능). 대안은 Blender SMPL-X add-on → USD/FBX(임포트 이슈), GRADE `animated_human_SMPL_to_USD`(SMPL/SMPL-H만, 구버전) | 원본 인간 모션과 로봇을 같은 stage에 시간 동기화해 비교. `omni.anim.retarget`은 NVIDIA Human 리그 캐릭터끼리만 지원하고 로봇 구동은 불가. `omni.anim.people`은 지원 중단 예정 |
| C. 외부 뷰어 | **aitviewer**(SMPL/SMPL-X/MANO, MIT), GMR MuJoCo 뷰어(영상 녹화), ProtoMotions `motion_libs_visualizer.py`(Isaac Lab/Isaac Gym), rerun(URDF 임포터), viser(holosoma), Blender SMPL-X add-on | 빠른 QA, 라벨링 검수 |

### 4.5 권장 툴체인 (로봇 모델 도착 전 → 후)

1. **프록시 로봇**
   - **Unitree G1 29 DoF**를 쓴다. 다리 12, 팔 7×2는 LG와 같고, 허리는 3 대 2이며, 목은 없다.
   - 사람 크기 스케일 튜닝에는 **H1-2**(7 DoF 팔)를 쓴다.
   - 목 링크가 필요하면 Unitree H2(SONIC과 soma-retargeter 지원, 목 DoF는 [미확인])를 검토한다.
2. **입력**
   - 자체 촬영은 GMR이 바로 읽는 포맷(Xsens BVH/MVN, OptiTrack FBX)으로 받는다.
   - 동시에 C3D → SOMA/MoSh++로 SMPL-X 정본을 만든다(라이선스는 1.6절 참조).
3. **리타겟**
   - **GMR을 주력**으로 한다. `smplx_to_lg.json` 템플릿을 미리 준비한다.
     - 링크 이름은 URDF가 오면 확정한다.
     - 회전 오프셋은 로봇 영점 자세와 SMPL-X T-pose 비교로 자동 계산한다.
     - 스케일은 URDF와 SMPL-X 분절 길이 비율로 정한다.
     - 허리 2 DoF는 spine3 회전에 낮은 가중치를 준다. 목 2 DoF는 head 회전만 추적한다.
   - PHC `fit_smpl_shape`와 ProtoMotions + PyRoki로 교차 검증한다.
   - 물체·지형이 있는 클립은 holosoma(OmniRetarget)를 검토한다.
4. **손**: dex-retargeting `position` 최적화로 2차 패스를 돈다(Allegro YAML을 4지 15 DoF로 수정, 손목 프레임 기준). 첫 GMT 반복에서는 손을 고정해도 된다.
   - AMASS 다수 서브셋에는 실제 손가락 캡처가 없다. **자체 촬영 시 장갑(Manus)이나 손가락 마커가 필수**다.
5. **1차 검증(MuJoCo)**: GMR 뷰어로 관절·속도 한계, 발 미끄러짐, 관통, 자기충돌을 본다.
6. **2차 검증(Isaac Sim)**
   - `batch_gmr_pkl_to_csv.py`로 CSV를 만들고, LG용으로 포크한 `csv_to_npz.py`/`replay_npz.py`를 돌린다.
   - 결과를 메타데이터 `validation`에 기록한다.
7. **학습 스택 선택**
   - GMT 공식 학습 코드가 아직 없다. BeyondMimic(가장 단순), **SONIC**(새 embodiment 가이드와 대규모 prior), ProtoMotions v3 중에서 고른다.
   - 모두 GMT 스타일 범용 트래킹으로 대체할 수 있다.
8. **데이터 증강(선택)**
   - NVIDIA **Kimodo**(text-to-motion, 2026-03)는 SMPL-X AMASS npz, G1 CSV, SOMA를 출력한다.
   - 모델 라이선스는 NVIDIA Open Model License(SOMA/G1)와 R&D License(SMPL-X 모델)로 나뉘며, 학습 데이터가 BONES-SEED다. 상업 적용 전에 확인이 필요하다.

---

## 5. 다음 단계 제안

1. **법무 검토 요청(최우선)**
   - SMPL-X/MoSh++ 상업 라이선스 필요 여부
   - AMASS 등 MPI NC 데이터의 1차년도 내부 사용 범위
   - 공개 5 h 라이선스(CC BY 4.0 권장)
   - 액터 동의서 문안
2. **자체 촬영 사양 확정**
   - 광학(OptiTrack/Vicon) + 손가락(Manus 또는 마커) + 물체 rigid body + 동기 영상 3~4뷰
   - IMU를 병행하면 MVNX `footContacts`를 확보할 수 있다.
3. **스키마 v0.1 확정**(1.5절) 및 `index.parquet` 기반 KPI 집계 스크립트 작성
4. **프록시 파이프라인 PoC**
   - CMU 원본 #143(박스·빨래바구니 운반)과 OMOMO 샘플을 GMR → G1 → Isaac Lab 2.3.2 kinematic replay로 돌려 end-to-end를 확인한다.
5. **태스크 정의 시 레퍼런스 영상 가이드 시트 작성**(3.3절 소스 기반)

---

## 6. 출처 (조사 중 실제 확인한 주요 URL)

**포맷 / 바디모델**
- AMASS: https://amass.is.tue.mpg.de/ , https://amass.is.tue.mpg.de/license.html , https://github.com/nghorbani/amass
- MoSh++ / SOMA: https://github.com/nghorbani/moshpp (mosh_head.py, run_tools.py, moshpp_conf.yaml), https://github.com/nghorbani/soma
- SMPL-X: https://github.com/vchoutas/smplx , https://smpl-x.is.tue.mpg.de/modellicense.html , https://smpl.is.tue.mpg.de/modellicense.html
- HumanML3D: https://github.com/EricGuo5513/HumanML3D (motion_representation.ipynb)
- BABEL: https://babel.is.tue.mpg.de/data.html
- BVH: https://research.cs.wisc.edu/graphics/Courses/cs-838-1999/Jeff/BVH.html
- FBX: https://docs.blender.org/manual/en/4.2/addons/import_export/scene_fbx.html , https://help.autodesk.com/cloudhelp/2020/ENU/FBX-API-Reference/cpp_ref/class_fbx_node.html
- C3D: https://www.c3d.org/ , https://github.com/pyomeca/ezc3d , https://github.com/EmbodiedCognition/py-c3d
- OpenSim TRC/STO: https://opensimconfluence.atlassian.net/wiki/spaces/OpenSim/pages/53089972/Marker+.trc+Files
- Xsens MVNX: https://audio-synch-tool.readthedocs.io/en/latest/_modules/audio_synch_tool/mvn.html , https://rofunc.readthedocs.io/en/latest/apidocs/rofunc/rofunc.devices.xsens.src.mvnx_file_accessor.html
- OptiTrack: https://docs.optitrack.com/motive/data-export/data-export-csv , https://docs.optitrack.com/motive/data-export/data-export-bvh
- USD / Omniverse: https://openusd.org/release/api/class_usd_skel_animation.html , https://docs.omniverse.nvidia.com/extensions/latest/ext_animation-retargeting.html , https://docs.omniverse.nvidia.com/extensions/latest/ext_asset-converter.html
- Isaac Sim 좌표 규약: https://docs.isaacsim.omniverse.nvidia.com/5.1.0/reference_material/reference_conventions.html
- Isaac Lab 3.0 마이그레이션: https://isaac-sim.github.io/IsaacLab/release/3.0.0/source/migration/migrating_to_isaaclab_3-0.html
- SOMA: https://arxiv.org/abs/2603.16858

**데이터셋**
- CMU: http://mocap.cs.cmu.edu/ , http://mocap.cs.cmu.edu/faqs.php
- LAFAN1: https://github.com/ubisoft/ubisoft-laforge-animation-dataset
- Motion-X: https://github.com/IDEA-Research/Motion-X , https://motion-x-dataset.github.io/
- BEAT2: https://huggingface.co/datasets/H-Liu1997/BEAT2 , https://pantomatrix.github.io/BEAT/
- GRAB: https://grab.is.tue.mpg.de/license.html
- ARCTIC: https://arctic.is.tue.mpg.de/license.html
- OMOMO: https://github.com/lijiaman/omomo_release , https://lijiaman.github.io/projects/omomo/
- BEHAVE: https://virtualhumans.mpi-inf.mpg.de/behave/license.html
- InterCap: https://intercap.is.tue.mpg.de/license.html
- ParaHome: https://github.com/snuvclab/ParaHome , https://jlogkim.github.io/parahome/
- TRUMANS: https://jnnan.github.io/trumans/ , https://github.com/jnnan/trumans_utils
- CIRCLE: https://tml.stanford.edu/circle_dataset/ , https://github.com/Stanford-TML/circle_dataset
- HUMOTO: https://jiaxin-lu.github.io/humoto/ , https://github.com/adobe-research/humoto
- Nymeria: https://www.projectaria.com/datasets/nymeria/ , https://github.com/facebookresearch/nymeria_dataset
- EgoBody: https://egobody.ethz.ch/
- HOI-M3: https://juzezhang.github.io/HOIM3_ProjectPage/ , https://huggingface.co/datasets/JuzeZhang/HOI-M3
- CORE4D: https://core4d.github.io/ , https://github.com/leolyliu/CORE4D-Instructions
- ACE-Data-0: https://ace-data-engine.github.io/ACE-Data-0/ , https://huggingface.co/datasets/ACERobotics/ACE-Data-0
- BONES-SEED: https://huggingface.co/datasets/bones-studio/seed , https://bones.studio/datasets/seed , https://bones.studio/info/seed-license
- HiPHI: https://huggingface.co/datasets/noitomrobotics/HiPHI
- Embody 3D: https://github.com/facebookresearch/embody-3d
- PHUMA: https://huggingface.co/datasets/DAVIAN-Robotics/PHUMA , https://arxiv.org/abs/2510.26236
- OmniRetarget: https://huggingface.co/datasets/omniretarget/OmniRetarget_Dataset , https://arxiv.org/abs/2509.26633
- AMASS→G1: https://huggingface.co/datasets/ember-lab-berkeley/AMASS_Retargeted_for_G1 , https://huggingface.co/datasets/fleaven/Retargeted_AMASS_for_robotics
- Unitree LAFAN1 retarget: https://huggingface.co/datasets/lvhaidong/LAFAN1_Retargeting_Dataset
- MMHOI: https://zenodo.org/records/17711786
- 100STYLE: https://www.ianxmason.com/100style/
- LINGO: https://github.com/mileret/lingo-release
- IMHD: https://github.com/AfterJourney00/IMHD-Dataset
- MotionMillion: https://huggingface.co/datasets/InternRobotics/MotionMillion
- Humanoid-X: https://huggingface.co/datasets/USC-GVL/Humanoid-X
- OakInk2: https://oakink.net/v2/
- HOT3D: https://www.projectaria.com/datasets/hot3D/license/
- GigaHands: https://ivl.cs.brown.edu/research/gigahands.html
- AIHub: https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71419 , https://aihub.or.kr/intrcn/guid/usagepolicy.do
- SFU: https://mocap.cs.sfu.ca/

**레퍼런스 영상**
- Ego-Exo4D: https://ego-exo4d-data.org/ , https://docs.ego-exo4d-data.org/
- Ego4D: https://ego4d-data.org/ (라이선스 초안 PDF: ego4d-data.org/pdfs/Ego4D-Licenses-Draft.pdf)
- EPIC-KITCHENS: https://epic-kitchens.github.io/2025
- HD-EPIC: https://hd-epic.github.io/
- Assembly101: https://assembly-101.github.io/
- HOI4D: https://hoi4d.github.io/
- Home Action Genome: https://homeactiongenome.org/
- Toyota Smarthome: https://project.inria.fr/toyotasmarthome/
- ETRI-Activity3D: https://ai4robot.github.io/etri-activity3d/ , https://ai4robot.github.io/etri-activity3d-livinglab/
- NTU RGB+D: https://rose1.ntu.edu.sg/dataset/actionRecognition/
- CMU-MMAC: http://kitchen.cs.cmu.edu/
- Breakfast Actions: https://serre.lab.brown.edu/breakfast-actions-dataset.html
- EgoLife: https://egolife-ai.github.io/
- Figure: https://www.figure.ai/news/helix-02 , https://www.youtube.com/watch?v=lQsvTrRTBRs , https://www.youtube.com/watch?v=CAdTjePDBfc , https://www.youtube.com/watch?v=Eu5mYMavctM
- 1X: https://www.youtube.com/watch?v=LTYMWadOW7c
- Tesla: https://www.youtube.com/watch?v=cpraXaw7dyc
- Unitree: https://www.youtube.com/watch?v=IiNbFPOUrz8
- Boston Dynamics: https://www.youtube.com/watch?v=HYwekersccY , https://bostondynamics.com/blog/large-behavior-models-atlas-find-new-footing/
- Apptronik/DeepMind: https://www.youtube.com/watch?v=ikZeU3wKVjM
- Agility: https://www.youtube.com/watch?v=rnFZAB9ogEE
- Physical Intelligence: https://www.youtube.com/watch?v=Zn8yMaepzVk , https://www.pi.website/blog/pi05
- Sunday Robotics: https://www.youtube.com/watch?v=a2HZyURUE_o

**툴링**
- GMR: https://github.com/YanjieZe/GMR (params.py, ik_configs/, scripts/smplx_to_robot.py, scripts/batch_gmr_pkl_to_csv.py)
- PHC: https://github.com/ZhengyiLuo/PHC (docs/retargeting.md)
- SMPLSim: https://github.com/ZhengyiLuo/SMPLSim
- ProtoMotions: https://github.com/NVlabs/ProtoMotions , https://nvlabs.github.io/ProtoMotions
- HumanoidVerse: https://github.com/LeCAR-Lab/HumanoidVerse
- ASAP: https://github.com/LeCAR-Lab/ASAP
- mink: https://github.com/kevinzakka/mink
- PyRoki: https://github.com/chungmin99/pyroki
- holosoma: https://github.com/amazon-far/holosoma
- soma-retargeter: https://github.com/NVIDIA/soma-retargeter
- Kimodo: https://github.com/nv-tlabs/kimodo , https://research.nvidia.com/labs/sil/projects/kimodo/
- Isaac Lab: https://github.com/isaac-sim/IsaacLab (humanoid_amp/motions/motion_loader.py, releases), https://isaac-sim.github.io/IsaacLab/v3.0.0-EA/source/refs/release_notes.html
- Isaac Sim: https://docs.isaacsim.omniverse.nvidia.com/latest/overview/release_notes.html
- BeyondMimic: https://github.com/HybridRobotics/whole_body_tracking (scripts/csv_to_npz.py, replay_npz.py)
- mjlab: https://github.com/mujocolab/mjlab
- GR00T-WBC / SONIC: https://github.com/NVlabs/GR00T-WholeBodyControl , https://nvlabs.github.io/GR00T-WholeBodyControl/
- GMT: https://github.com/zixuan417/humanoid-general-motion-tracking
- TWIST / TWIST2: https://github.com/YanjieZe/TWIST , https://github.com/amazon-far/TWIST2
- PBHC: https://github.com/TeleHuman/PBHC
- MimicKit: https://github.com/xbpeng/MimicKit
- OpenTrack: https://github.com/GalaxyGeneralRobotics/OpenTrack
- dex-retargeting: https://github.com/dexsuite/dex-retargeting
- aitviewer: https://github.com/eth-ait/aitviewer
- GRADE SMPL→USD: https://github.com/eliabntt/animated_human_SMPL_to_USD

**확인 실패·제한**
- HF `unitreerobotics/LAFAN1_Retargeting_Dataset`: 401
- ParaHome LICENSE 파일: 404
- AMASS 하위 라이선스 디렉터리: 403
- Charades 공식 페이지: allenai.org로 리다이렉트
- ETRI nanum 포털: 접속 거부
- holosoma `ADD_ROBOT_TYPE_README.md`: 404
- Isaac Sim 5.0 릴리스 노트: 404

본문의 [미확인] 항목은 위 이유로 1차 출처 확인이 되지 않은 것이다.
