---
name: retlens
description: Drive RetLens (Retarget Lens), the tool that retargets human mocap (BVH, FBX, AMASS SMPL-X, C3D markers) to a humanoid robot (Unitree G1 by default, or any humanoid's MJCF / URDF) and validates it - QC, smoothness / foot / balance metrics, overlay comparison of two motions, MuJoCo / Isaac Sim physics checks and Isaac videos. Use it when the user asks to retarget or check mocap, compare motions or capture sources, find what is wrong with a clip, run a physics check, inspect C3D marker quality, or show / operate something in the open RetLens window. Commands give JSON; a running window has a local HTTP API.
---

# RetLens로 일하기 (AI용 안내)

RetLens는 사람 모션캡처를 휴머노이드 로봇으로 옮기고(리타게팅, GMR) 그 결과를 검증하는 데스크톱 프로그램입니다. 로봇은 기본이 Unitree G1이고, 환경 설정의 로봇 모델(또는 `--robot`)에 다른 휴머노이드의 MJCF·URDF를 주면 그 로봇으로 합니다. AI는 두 가지 방법으로 다룹니다.

| 방법 | 언제 | 무엇 |
|---|---|---|
| **명령줄 `retlens-cli`** | 창 없이 계산만 할 때, 여러 파일을 한꺼번에 볼 때 | 리타게팅, QC·지표, 겹쳐 비교 수치, 시간 정렬, C3D 마커 QC, 물리 검사(MuJoCo·Isaac), Isaac 녹화. 결과는 JSON 한 덩어리 |
| **로컬 HTTP API** | 사용자가 RetLens 창을 띄워 두었고, 화면에서 무언가를 보여 주거나 조작할 때 | 모션 열기, 재생·탐색, 겹쳐 비교 켜기, 물리 모드, 지표, 스크린샷 |

두 방법 모두 창과 같은 코드(`retlens/app/scene.py`의 MotionScene)를 써서 숫자가 화면과 같습니다.

## 1. 실행 방법 찾기

- **저장소(개발)에서:** `conda run -n retlens python tools\retlens_cli.py <명령> ...` (저장소 루트에서). 창은 `scripts\editor.bat`.
- **설치판:** 설치 폴더의 `retlens-cli.exe <명령> ...`(`RetLens.exe` 옆).
- 먼저 `retlens-cli info`로 환경을 확인하세요. 파일 위치, 각 기능에 필요한 외부 프로그램(Isaac Sim, Blender, SMPL-X 모델)이 있는지(`checks`), Isaac 라이선스 동의 여부(`isaac_eula_accepted`)가 나옵니다.
- 출력은 stdout의 JSON 한 줄입니다(`--pretty`면 들여쓰기, 명령 앞뒤 어디에 붙여도 됨). 진행 메시지는 stderr로 나옵니다.
- 실패하면 종료 코드가 1이고 `{"error": "..."}`를 출력합니다. 명령이나 옵션을 잘못 써도 같습니다.
  - `physics`와 `video --physics`는 물리 계산이 실패하거나 `--timeout`(기본 1200초) 안에 끝나지 않아도 1입니다(`physics`는 결과와 함께 `error`).
  - 여러 모션을 다루는 `autolabel`·`summary`·`batch`·`export`·`c3d-qc`는 모두 실패하면 1, 일부만 실패하면 2입니다. 물리 검사가 실패한 모션은 `batch`에서는 2로 알리고, `export`에서는 실패로 셉니다(`--allow-falls`면 `phys_error`를 붙여 쓰고 2).
  - 모션을 여는 명령(`inspect`·`metrics`·`compare`·`align`·`physics`·`video`·`retarget`)은 없는 파일이면 장면을 띄우기 전에 바로 `"없는 파일: …"` 오류(1)입니다.

## 2. 명령줄 `retlens-cli`

| 명령 | 하는 일 | 주요 출력 |
|---|---|---|
| `info` | 버전, 파일 위치, 환경 점검 | `locations`, `checks[]`(key, ok, needed_for, hint), `isaac_eula_accepted` |
| `robot [MODEL]` | 로봇 모델(기본은 환경 설정, 비면 G1)에서 리타게팅이 찾은 부위: 다리·팔의 관절(proximal / bend / distal, `*`는 비틀림), 무릎·팔꿈치 굽힘 방향(`flex_sign`), 손·발 몸체, IK 대상 몸체, 키·서 있는 골반 높이, 손가락(`fingers`: 손가락마다 관절과 손을 오므리는 방향, 예 `left_hand_index_0_joint (-)`; 0은 벌림·비틀림이라 안 움직임; 비면 손가락 관절 없음), `notes`(예: 허리 pitch 없음, 토크 한계 없는 관절 수 "torque limits missing on N joints"). 못 찾으면 `error`에 무엇을 못 찾았는지 | `robot`(name, dof, legs, arms, tasks, height_m, fingers, notes) |
| `library [--query Q] [--limit N]` | 모션 폴더의 파일 목록. Q는 파일 이름과 CMU 동작 설명에서 찾음(예: `143_11`, `walk`, `dance`) | `files[]`(path, folder, name, cmu_description) |
| `inspect FILE...` | 열고(필요하면 리타게팅, 캐시) 모션 하나하나의 정보 | `motions[]`(id, kind, frames, fps, duration_s, qc, qc_notes, ik_position_residual, retarget, foot_flat, foot_reference, self_collision, fingers, metrics, retarget_quality, c3d, solved_motion, warnings, objects, prop_files) |
| `metrics FILE... [--ref N]` | 창의 "분석" 표와 같은 표. 기준(ref, 기본은 첫 파일) 대비 RMSE 포함 | `rows`, `motions[].values`, `row_help` |
| `compare A B [--tol 3] [--no-heading] [--align]` | 겹쳐 비교: B를 A의 골반에 맞춰 부위별 차이(cm). `worst_moments`의 `time_s`는 타임라인 시각이고, B 자신의 시각은 `time_s − offsets_s.b`. `tol_cm`은 실제로 쓴 값 | `regions[]`(region, mean_cm, max_cm, max_at_s, beyond_tol_pct), `worst_moments[]`, `offsets_s`(a, b), `tol_cm`, `--align`이면 `align_notes` |
| `align REF FILE...` | 기준에 시간 자동 정렬(다리 관절각이 가장 잘 맞는 오프셋) | `offsets_s`, `notes` |
| `retarget FILE --out OUT.npz [--smooth 6] [--foot-flat] [--swing-clearance CM] [--self-collision]` | 리타게팅해서 로봇 모션 npz(+ json)로 저장. `--out`은 `.npz`(확장자가 없으면 붙이고, `.NPZ`도 `.npz`로 씀). 다른 확장자나 입력 파일 자체면(경로를 8.3 짧은 이름 등으로 다르게 써도) 오류. 폴더는 먼저 만듦 | `out`, `frames`, `fps`, `kind` |
| `autolabel FILE... [--rules R.yaml] [--out DIR] [--summary]` | 자동 라벨: 규칙 파일대로 사람 동작을 보고 구간 라벨(리타게팅 없이). `--out`이면 라벨을 붙인 모션마다 그 폴더 안에 `<이름>.labels.csv`(구간이 없으면 열 이름만). 이름이 겹치면 원래 폴더 구조를 그 아래에, 같은 폴더의 `X.c3d`·`X.bvh`는 `c3d\`·`bvh\` 아래에 둠. 실패한 모션은 지난 실행의 CSV를 지움. `--out`이 모션의 폴더이거나 같은 이름의 모션이 든 폴더면 아무것도 쓰거나 지우지 않고 종료 코드 1. 종료 코드 1 = 모두 실패, 2 = 일부 실패 | `rules`, `motions[]`(file, labels{auto, tracks, segments[], notes, error}, csv, csv_removed) |
| `batch FILE\|DIR... [--physics] [--rules R.yaml] [--csv OUT.csv]` + 리타게팅 보정 옵션 | 데이터셋 일괄 처리: 폴더 아래 모션마다 리타게팅·측정한 한 줄(점수, QC, 주된 감점, 문제 구간 초, 품질·발 지표, 물체 닿음, 라벨, `--physics`면 MuJoCo 보조 힘 결과와 `phys_first_cause`(첫 넘어짐 원인)·`phys_fall_causes`(원인별 횟수, 클립 안)·`phys_torque_limits_missing`(토크 한계 없는 관절 수)). 그 밖의 행 키: `file_warnings`(읽을 때 뺀 것, `; `로 이음, CSV 열 "파일 주의"), C3D면 `solved_motion`(쓴 솔버 결과)·`solved_elsewhere`(true: 모션 폴더에서 찾음)·`take_warning`(다른 촬영일 수 있음, CSV 열 "촬영 주의"). C3D 행의 `objects`·물체 닿음은 솔버 결과의 물체. 파일·옆의 라벨 파일·설정(C3D는 솔버 결과와 그 물체 파일도)별로 캐시되어 다시 돌리면 끝난 것은 바로 나옴(옆의 라벨 파일을 더하거나 고치면 그 행은 다시. 폴더의 `labels.csv`·`labels.json`을 고치면 다시 재지 않고 라벨만 다시 읽음). 물리 검사를 하지 못한 행은 `phys_error`(CSV 열 "물리 오류")가 있고 다음에 다시 시도. 폴더에서는 라벨 파일, SMPL-X 체형 파일, Unitree 로봇 csv가 아닌 csv 표, 함께 처리하는 사람 FBX가 쓰는 물체 파일, 그 아래의 `retlens_export` 폴더(직접 주면 읽음)를 뺌. 종료 코드 1 = 모두 못 읽음, 2 = 일부 못 읽음 또는 물리 검사 실패 | `motions`, `read`, `errors`, `total_s`, `qc_fail`, `qc_warn`, `with_falls`, `first_fall_causes`({원인: 모션 수}), `phys_errors`, `labelled`, `rows[]`, `csv` |
| `export FILE\|DIR... --out DIR [--qc PASS\|WARN\|FAIL] [--min-score N] [--physics] [--allow-falls] [--cut] [--cut-kinds K,K] [--pad S] [--min-piece S] [--range START END] [--formats npz,csv,pkl] [--no-labels]` + 리타게팅 보정 옵션 | 데이터셋 내보내기: `batch`(캐시 공유)를 거쳐 기준을 넘는 모션을 `--out`에 입력 폴더 구조대로 씀(모션마다 `<이름>.npz` 등 + `.labels.csv` + `.json`, 맨 위에 `manifest.json`·`manifest.csv`). `--qc`는 넣을 가장 나쁜 판정(기본 WARN). `--min-score`는 리타게팅 점수 하한(로봇 모션 파일은 점수가 없어 받지 않음). `--physics`면 넘어진 모션을 뺌(`--allow-falls`면 둠). `--cut`은 QC가 못 쓰는 프레임, `--cut-kinds`의 문제 구간(기본 `penetration,marker_gap`; `slip`, `swing_low`, `self_collision`, `joint_limit`도 됨), 넘어짐 1초 전–0.25초 뒤를 잘라 `--min-piece`초(기본 1) 이상 남은 조각을 `<이름>_<시작>-<끝>s`로 씀(조각마다 QC 다시 판정, 창의 QC처럼 정적 불균형 포함). `--range`는 모션 하나의 시간 범위만(조각처럼 QC 다시 판정). 통째로 쓰는 모션의 `qc`는 `batch` 행의 QC. 같은 폴더에 다시 내보내면 이전 manifest에 적힌 파일만 지우고 새로 씀. 한 폴더의 같은 촬영(`X.bvh`·`X.fbx`·`X_stageii.npz`·`X.c3d`)은 하나만: bvh → fbx → npz → csv → pkl → c3d 순으로 읽을 수 있는 첫 파일을 판정하고, 나머지는 `excluded`에 "같은 촬영: X로 내보냄"(X를 씀) 또는 "같은 촬영: X을(를) 씀"(X를 판정했지만 쓰지 않음). 입력 폴더 아래의 `retlens_export` 폴더는 읽지 않음(직접 주면 읽음). csv는 x y z qx qy qz qw + 관절각(머리글 없음, 늘 30 fps), pkl은 GMR. `--physics`면 물리 검사를 하지 못한 모션도 뺌(이유 "물리 검사 실패: …"). `--allow-falls`면 넣고(넘어짐은 보지도 자르지도 않음) 그 clip에 `phys_error`, `totals.phys_errors`에 셈. manifest의 clip에는 `phys_error`·`file_warnings`(없으면 null), csv로 쓴 것은 `csv_fps`·`csv_frames`도. 원본을 덮어쓰지 않음(경로를 8.3 짧은 이름·연결 드라이브·정션·심볼릭 링크로 다르게 써도 같은 파일로 봄): 내보내는 모션이 이번에 읽는 원본 모션이 든 폴더에 들어가게 되면(예: `--out`이 입력 폴더의 바로 위 폴더, 파일을 줄 때 그 파일의 폴더), 또는 없는 입력이 있으면 아무것도 지우거나 쓰지 않고 오류. `--out`이 입력 폴더 아래면 그 안의 파일과 이전 export가 쓴 파일은 모션으로 읽지 않음. Ctrl+C로 끊어도 거기까지를 manifest에 적음(`stopped`). 종료 코드 1 = 모두 실패(못 읽음, 내보내기 실패, 물리 검사 실패), 2 = 일부, 또는 `--allow-falls`로 물리 오류인 모션을 넣음 | `out`, `manifest`, `totals`(motions, exported_motions, clips, seconds, cut_seconds, short_seconds, cut_by_kind, excluded, excluded_by_reason, phys_errors), `clips[]`(files, source, start_s, end_s, duration_s, qc, labels, 있으면 phys_error·file_warnings), `excluded[]`(source, reason) |
| `version` | 버전만(아무것도 불러오지 않아 빠름) | `app`, `version` |
| `update` | 업데이트 확인만: GitHub 최신 릴리즈를 이 버전과 비교(설치하지 않고 실행한 RetLens면 이 버전과 이 PC에 설치된 버전 중 새것과 비교). 내려받거나 설치하지 않음; 설치·업데이트는 사용자가 창의 도움말 > 업데이트 확인에서. 종료 코드 1 = 확인 실패 | `current`, `latest`(version, sha256, asset_url, notes...), `newer`, `installed_version`(이 PC에 설치된 버전, 설치하지 않고 실행할 때만), `installed`(설치 폴더에서 실행 중), `portable`, `install_dir`, `releases_page`, `error` |
| `summary FILE\|DIR... [--rules R.yaml] [--csv OUT.csv]` | 데이터셋 요약(리타게팅 없이): 폴더 아래 모션마다 길이, 라벨(옆의 라벨 파일, `--rules`면 자동 라벨) 트랙·라벨별 시간, FBX 물체. 폴더별·라벨별 합계. 한 폴더의 같은 촬영(`X.bvh`·`X.fbx`)은 export처럼 읽을 수 있는 첫 파일로 하나만 세고(나머지 행은 `same_take`: 센 파일, 그 FBX의 물체는 센 행에 합침), 관절 8개 미만 FBX(물체 파일)는 `not_counted`. `warnings`는 읽을 때 뺀 것(예: FBX의 다른 사람 골격, 목록 또는 null; `--csv`에는 "error" 뒤 warnings 열). 아래의 `retlens_export` 폴더는 읽지 않음. `per_folder` 키는 입력들의 공통 상위 폴더 아래 경로(예: `day1/s01`). 종료 코드 1 = 모두 못 읽음, 2 = 일부 못 읽음 | `motions`, `failed`, `total_s`, `total_h`, `per_folder`, `per_label`(seconds, segments, share_pct), `files[]`(duration_s, labels, label_seconds, objects, error, warnings, same_take, not_counted), `csv` |
| `c3d-qc FILE.c3d...` | C3D 원본 마커 QC만(리타게팅 없이). 결과는 파일 이름별(이름이 겹치면 경로별). 읽지 못한 파일은 `{"error"}`이고 나머지는 그대로 나옴. 종료 코드 1 = 모두 실패, 2 = 일부 | `{파일 이름: {markers(마커 수), missing_pct, most_missing, longest_gap_s, spike_frames, ...}}` |
| `physics FILE [--balance harness]` | 물리 검사. 기본은 MuJoCo 골반 보조 힘(클립당 몇 초, 라이선스 동의 불필요). `--balance pd`/`gmt`는 MuJoCo 제어기 없음 / GMT, `isaac [--assist 1]`은 Isaac PhysX(짧은 클립 약 1분, EULA 동의 필요) | `physics.metrics`(phys_falls, phys_fall_causes, phys_harness_pct, phys_saturated_pct, phys_body_error_cm, phys_ok, 토크 한계 없는 관절이 있으면 phys_torque_limits_missing), `physics.falls[]`(`time_s`, `cause`(한글), `cause_id`, `onset_s`, `rule`(MuJoCo 판정), `after_clip`, `evidence`, `others`), `physics.first_fall_cause` |
| `video FILE [--out X.mp4] [--physics [--balance B]]` | Isaac으로 녹화(EULA 동의 필요). `--physics`면 그 균형 제어로 시뮬레이션한 결과를 녹화(계산이 실패하면 녹화하지 않고 종료 코드 1) | `video` 경로 |
| `setup [--offline]` | 설치 도우미 점검: Blender·GMT·Isaac Sim·SMPL-X가 이 PC에 있는지, 없으면 설치할 수 있는지(GPU·드라이버·디스크·인터넷·쓰기 권한) | `components[]`(key, state, action, found, detail, note, requirements[], license) |
| `setup --install KEY [--accept-license] [--source ZIP]` | 그 구성 요소를 필요할 때만 설치. 이미 호환되는 것이 있으면 아무것도 받지 않음 | 설치 뒤 상태 |
| `api` | 떠 있는 창의 HTTP API 주소와 토큰 | `url`, `token` |
| `install-skill [--project DIR]` | 이 안내를 Claude Code 스킬 폴더에 복사 | `installed` |

- **모션 파일:**
  - 사람 모션: BVH(관절 이름의 공백·UTF-8 BOM 됨), FBX(Blender 필요, 바이너리 FBX만), AMASS SMPL-X `*_stageii.npz`(SMPL-X 모델 필요), C3D.
  - 로봇 모션: npz, Unitree csv(머리글 없이 숫자만 8열 이상. `#` 주석 줄·줄 끝 주석(`np.savetxt`의 `header=`)은 건너뜀. 다른 csv 표는 모션 목록·`batch`에서 빠짐), GMR pkl.
  - 잘렸거나 손상된 로봇 csv는 "N번째 줄의 열이 …" / "N번째 줄 M번째 칸(…)을 숫자로 읽지 못했습니다"(N은 주석·빈 줄도 센 파일의 줄 번호), 깨졌거나 다른 형식의 pkl은 "GMR pkl 모션 파일이 아닙니다" 오류입니다.
  - 사람 모션은 처음 열 때 리타게팅합니다. 처음에는 몇 초에서 수십 초가 걸리고, 다음부터는 캐시에서 바로 나옵니다. RetLens 업데이트로 리타게팅 방식이 바뀌면 한 번 다시 계산합니다.
  - 파일 읽기에서 빠진 것이 있으면 `inspect`·`/api/motion`에 `warnings`(목록)가 나옵니다. 예: FBX의 다른 사람 골격, 사람이 아닌 큰 골격(관절 8개 이상).
- **리타게팅 보정:** 모션을 여는 명령(`inspect`, `metrics`, `compare`, `align`, `retarget`, `batch`, `export`, `physics`, `video`)은 사람 모션을 어떻게 리타게팅할지 정하는 옵션을 받습니다. 로봇 모션은 그대로 엽니다.
  - `--robot MODEL`: 리타게팅할 로봇. `unitree_g1`, `unitree_g1_with_hands` 또는 휴머노이드의 MJCF(.xml)·URDF(.urdf) 경로(기본은 환경 설정 > 로봇 모델, 비면 G1). RetLens에 든 G1 모델 파일의 경로는 그 내장 모델로 봅니다(이전 버전에서 그 경로로 만든 모션·세션도 그 내장 G1의 것으로 봐 `robot_mismatch`가 없음). 처음 쓰는 로봇은 `robot MODEL`로 부위가 맞게 찾아졌는지 먼저 봅니다. 결과 캐시는 모델 파일 내용으로 구분됩니다.
  - `--smooth HZ`: 평활화(기본 6, 0 = 끔). 0이 아니면 0보다 크고 15보다 작아야 합니다(30 fps의 절반).
  - `--foot-flat`: 디딤발 평평 보정.
  - `--swing-clearance CM`: 스윙 발 보정(권장 2, 0–10).
  - `--self-collision`: 자기 관통 보정. 바꾼 내용은 `self_collision`(바뀐 프레임 수, 3 cm 넘게 파고든 프레임 전→후, 가장 깊은 곳 전→후, 남은 부위 쌍과 그 프레임 수 `unresolved_pairs`)에 있습니다.
  - 설정마다 캐시가 따로 있어서 보정 전후를 각각 열 수 있습니다. 어떤 설정으로 만들었는지는 `retarget`(smooth_hz, foot_flat, swing_clearance_cm, self_collision)에 나옵니다. 디딤발 평평 보정이 바꾼 내용은 `foot_flat`(바뀐 프레임 수, 디딤 중 발 pitch·기울기 전→후, 골반을 낮춘 높이 `root_drop_cm`, 두 발 높이차 `two_feet_height_diff_cm`)에 있습니다.
- **C3D:** 마커만으로는 로봇을 움직일 수 없습니다. 같은 이름의 솔버 결과(BVH → FBX → AMASS 순)를 C3D와 같은 폴더에서 먼저, 없으면 기본 모션 폴더에서 찾아 그것을 리타게팅하고, 마커를 옆에 그립니다. 없으면 오류가 납니다.
  - 쓴 파일은 `solved_motion`입니다. `c3d.solved_elsewhere`가 true면 기본 모션 폴더에서 찾은 것입니다.
  - `c3d.take_warning`이 있으면 다른 촬영일 수 있습니다. 마커 골반이 솔버 결과의 골반과 평균 20 cm 넘게 떨어져 있거나, 10 cm 넘게 떨어져 있고 C3D와 솔버 결과의 길이가 5% 넘게 다를 때입니다(이때는 두 길이도 적힘). 같은 촬영도 골격 루트 위치 때문에 11 cm 안팎 떨어질 수 있습니다. 보고할 때 함께 적습니다.
  - C3D의 `objects`·`prop_files`와 손–물체 지표는 솔버 결과의 물체입니다(창의 3D 화면에는 그리지 않음).
  - C3D도 솔버 골격과 비교한 `retarget_score`·품질 지표가 나옵니다(그 솔버 결과를 연 것과 같은 값).

## 3. 로컬 HTTP API (떠 있는 RetLens 창)

- 창이 떠 있으면 `127.0.0.1`의 기본 포트 8765에서 동작합니다(사용자가 "환경 설정 > AI 연동"에서 끌 수 있음).
- **주소와 토큰:** `retlens-cli api`, 또는 사용자 데이터 폴더의 `api.json`에서 읽습니다(설치판 `%LOCALAPPDATA%\RetLens\api.json`, 저장소 `data\api.json`). 토큰은 창을 켤 때마다 바뀝니다.
- 모든 요청에 `Authorization: Bearer <token>` 헤더가 있어야 합니다. 웹 페이지의 요청(`Origin` 헤더)은 거부합니다.
- 응답은 `{"ok": true, ...}` 또는 `{"ok": false, "error": "..."}`이고, 오류면 HTTP 코드도 4xx/5xx입니다.
- **값 검사:** 참/거짓 값은 `true`/`false`, `1`/`0`, `"true"`/`"false"`/`"yes"`/`"no"`/`"on"`/`"off"`를 받습니다. `/api/labels`의 `auto`와, `/api/labels`·`/api/session`의 `"save": true`도 같습니다(`"save": "true"`, `?auto=1`). 그 밖의 값, 숫자가 아니거나 범위 밖의 숫자는 400이고 아무것도 바뀌지 않습니다.
  - 쿼리 문자열에 같은 키를 여러 번 쓰면 목록입니다(`?paths=a&paths=b`는 둘 다 엶). 목록을 받지 않는 값이면 400(id는 404)입니다.
  - 범위: `offset_s` ±600, `speed` 0.01–16, `tol_cm` 0.5–50, `time_s` 유한한 수, `problem` 1 또는 -1, `assist` 0 이상.

```powershell
$api = Get-Content "$env:LOCALAPPDATA\RetLens\api.json" | ConvertFrom-Json      # 저장소에서는 data\api.json
$h = @{ Authorization = "Bearer $($api.token)" }
Invoke-RestMethod "$($api.url)/api/status" -Headers $h
Invoke-RestMethod "$($api.url)/api/open" -Method Post -Headers $h -ContentType "application/json" `
  -Body (@{ paths = @("C:\data\02_01.bvh", "C:\data\02_01_stageii.npz") } | ConvertTo-Json)
```

| 요청 | 내용 |
|---|---|
| `GET /api/help` | 모든 엔드포인트 |
| `GET /api/status` | 시각, 재생 상태, 물리 모드, 겹쳐 비교, 열린 모션, `robot`(창의 로봇: name, builtin, model, digest, dof, height_m, notes). 모션에 `robot_mismatch`가 있으면 다른 로봇의 모션일 수 있다는 뜻(관절은 이름으로 맞추고 나머지는 0). 로봇 이름이 같은데 나오면 모델 파일이 바뀌었거나 이전 버전 RetLens에서 만든 모션(원본을 다시 리타게팅하면 없어짐) |
| `GET /api/checks` | 환경 점검 |
| `GET /api/library?query=walk` | 모션 파일 목록 |
| `POST /api/open {"paths": [...]}` | 열기(창에 나타나고 선택됨). `paths`는 목록 또는 경로 하나. 먼저 모든 파일을 검사해, 없는 파일이면 404, 작업 세션(`.retlens`, `/api/session {"open"}`으로)이나 라벨 파일(`/api/labels {"id", "path"}`로)이면 422이고 아무것도 열지 않음. 같은 촬영의 물체 FBX는 열지 않고 `skipped[]`(path, why)에 적음(사람 FBX와 함께 주면 그 모션에 그려짐. 그 사람이 쓰지 않는 같은 이름의 사본이면 why가 "another copy of this take's prop file is drawn with the person's motion (같은 이름의 <폴더> 파일을 씀)". 물체 FBX만 주면 422). 그다음 하나씩 열고 열지 못한 파일은 `failed[]`(path, error)에 적으므로 꼭 확인. 하나도 못 열었을 때만 오류(모두 읽을 수 없는 파일이면 422, 그 밖은 500) |
| `POST /api/retarget {"foot_flat"?, "swing_clearance_cm"?, "self_collision"?}` | 리타게팅 보정(창의 "리타게팅" 메뉴). 다음에 여는 사람 모션부터 적용되고, 이미 연 모션은 그대로입니다. `swing_clearance_cm`이 0–10 밖이거나 숫자가 아니면 400이고 아무 보정도 바뀌지 않음. 지금 설정은 `/api/status`의 `retarget` |
| `POST /api/remove {"id", "discard_edits"?}` | 닫기. 라벨에 저장하지 않은 편집이 있으면 409(`discard_edits: true`는 사용자가 버려도 된다고 했을 때만) |
| `GET /api/motion?id=...` | 모션 하나의 QC·지표·C3D·물리·구간 라벨. 라벨 정의 파일(이 모션의 자동 라벨 규칙 파일과 설정의 자동 라벨 규칙)이 있으면 `label_definitions {files, tracks: {트랙: [라벨...]}}`(라벨을 고칠 때 고를 이름, 파일 순서) |
| `POST /api/item {"id", "visible"?, "offset_s"?, "show_human"?}` | 보이기, 시간 오프셋, 사람 스켈레톤 |
| `POST /api/labels {"id", "path"?}` | 구간 라벨: `path` 파일을 붙임 / `"path": null`이면 뺌 / `path`가 없으면 다시 읽음(모션 옆에서 찾은 라벨은 열 때처럼 다시 찾고, 고른 파일은 그 파일을) |
| `POST /api/labels {"id", "auto": true, "rules"?}` | 자동 라벨: 규칙 파일(`rules`, 없으면 사용자가 고른 설정)대로 붙임. 붙일 수 없으면(로봇 모션, 깨진 규칙) 422이고 라벨은 그대로. 저장하지 않은 편집이 있으면 위 둘과 함께 409(`discard_edits: true`) |
| `POST /api/labels {"id", "edit", "index"?, "expect"?, ...}` | 라벨 편집(창과 같은 한 단계, Ctrl+Z로 되돌림): `bounds {"start_s"?, "end_s"?}`, `rename {"label"}`, `split {"time_s"}`, `delete`, `merge {"with": "next"\|"prev"}`, `add {"track", "time_s", "label"}`(그 시각의 빈칸을 채움), `undo`, `redo`. `index`는 `labels.segments`의 순서, `expect {"label", "start_s"}`가 다르면 409(그사이 바뀜). 시간은 모션 초, 프레임에 맞춰짐. 시간이 숫자가 아니면 422. 답의 `segment`는 편집한/새 구간의 순서. `labels.unsaved_edits`, `undo`, `redo`. `rename`·`add`의 라벨은 되도록 `GET /api/motion`의 `label_definitions`에서 고릅니다(이 모션에 아직 없는 정의 라벨은 규칙 파일의 긴 이름·색을 씀) |
| `POST /api/labels {"id", "save": true \| "D:/x.labels.csv", "overwrite"?}` | 라벨을 CSV로 저장(`true`: 모션 옆 `<이름>.labels.csv`). 있는 파일은 `overwrite: true`일 때만(무엇을 잃는지 409 메시지에), 폴더의 여러 모션 표·라벨 파일이 아닌 파일에는 저장하지 않음 |
| `GET /api/session` | 작업 세션: 열린 세션 파일(`path`), 바뀜(`dirty`), 여는 중이면 `restoring {done, total, current}`, 열지 못한 모션(`unresolved`: 그 파일을 창이나 `/api/open`으로 열면 빠짐) |
| `POST /api/session {"save": true \| "C:/x.retlens", "overwrite"?}` / `{"open": PATH, "mode": "replace"\|"add", "discard_changes"?}` | 작업 세션 저장 / 열기(열린 모션, 보정, 시간 오프셋, 보이기, 라벨(고친 것 포함), 겹쳐 비교, 씬 설정, 물리 모드, 재생 위치). 저장은 파일을 쓸 수 없으면 500(이유 포함, 창에 대화 상자는 뜨지 않음), 세션을 여는 중이면 409. 여는 것은 바로 돌아오고 `GET /api/session`의 `restoring`이 없어질 때까지 기다린 뒤 `last_open`(열린 모션, `failed`, `notes`: 다른 로봇이나 바뀐 모델 파일로 저장한 세션이면 그 알림도)을 봅니다. 모션이 열려 있으면 `mode`가 필요(409). `replace`는 열린 세션에 저장하지 않은 변경이 있거나, 세션 파일이 없는 작업에 저장하지 않은 라벨 편집이 있으면 409(`discard_changes`). `add`는 모션만 더하고(씬 설정·물리·겹쳐 비교는 그대로), API로 열면 물리 모드는 MuJoCo 보조 힘·없음만 다시 켭니다(GMT·Isaac은 꺼진 채, `notes`에 나옴) |
| `POST /api/playback {"play"?, "time_s"?, "speed"?, "loop"?}` | 재생/정지, 시각 이동(`speed` 0.01–16) |
| `GET /api/metrics?ref=...` | 분석 표 |
| `POST /api/align {"ref"}` | 시간 자동 정렬 |
| `POST /api/compare {"a", "b", "heading"?, "tol_cm"?}` / `{"on": false}` | 겹쳐 비교를 켜고 수치 받기 / 끄기. `tol_cm`은 0.5–50. 답은 `compare`와 같고 `offsets_s` {a, b}(두 모션의 시간 오프셋: `worst_moments`의 `time_s`는 타임라인 시각, B 자신의 시각은 `time_s − offsets_s.b`) |
| `POST /api/playback {"problem": 1 \| -1, "id"?}` | 다음 / 이전 문제 시작으로(그 모션, 없으면 보이는 모든 모션). `GET /api/motion`의 `problems`는 종류별 `[시작, 끝]`(slip·penetration·swing_low·self_collision·joint_limit·marker_gap·fall) |
| `GET/POST /api/batch` | 창의 데이터셋 탭에서 일괄 처리: `{"folders", "physics"?, "auto_labels"?}`로 시작(`folders`는 폴더·모션 파일의 목록 또는 하나, 없는 것이 있으면 404), `{"stop": true}`, GET은 진행(`running`)·합계(`phys_errors` 포함)·지금까지의 행 |
| `GET/POST /api/segments` | 유형별 재생: 열린 모션들의 "트랙: 라벨" 목록(구간 수·초). `{"key", "solo"?, "play"?}`로 그 라벨 구간을 차례로 재생, `{"step": ±1}`, `{"stop": true}` |
| `POST /api/retarget {"id", "foot_flat"?, "swing_clearance_cm"?, "self_collision"?}` | 그 모션만 다른 보정으로 다시 리타게팅해 같은 자리에(`score_before`, `score`). 라벨, 시간 오프셋, 겹쳐 비교의 A·B 자리는 그대로. `swing_clearance_cm`이 0–10 밖이거나 숫자가 아니면 400(아무것도 바뀌지 않음). `{"id", "recommend": true}`는 보정 조합 8가지의 리타게팅 점수 순위(처음엔 몇 분) |
| `POST /api/physics {"on", "assist"?, "balance"?}` | 물리 모드. `balance`: `harness`(MuJoCo 보조 힘, 기본) / `pd`(MuJoCo 제어기 없음) / `gmt`(MuJoCo GMT 추적 정책) / `isaac`(Isaac 보조 힘, `assist` 배율, EULA 동의 필요). 결과는 `/api/jobs`·`/api/motion`으로 확인 |
| `POST /api/video {"id"}` | 동영상 저장(대기열) |
| `GET /api/jobs` | 물리(Isaac·MuJoCo)·동영상 작업 상태와 결과 경로 |
| `POST /api/camera {"fit": true}` | 카메라 맞추기 |
| `POST /api/screenshot {"path"?}` | 창 스크린샷 PNG(경로를 돌려줌, 이미지로 읽어 확인 가능) |

- `id`는 모션 라벨(`"cmu_bvh/02_01"` 처럼 폴더/파일 이름, 한 장면에서 유일)입니다. 순서 번호(0부터), 파일 이름, 절대 경로(슬래시 방향·대소문자, 8.3 짧은 이름 `C:\Users\ABCDEF~1\...` 무관)도 됩니다. 파일 이름이나 경로가 열린 모션 여럿에 맞으면(같은 파일을 두 번 열었거나 다른 폴더의 같은 이름 파일) 409이니 라벨을 씁니다. 404·409 메시지에는 보낸 id가 그대로 나옵니다.

## 4. 알아야 할 개념

- **손가락:** 로봇 손에 손가락 관절이 있으면(예: 내장 `unitree_g1_with_hands`), 리타게팅이 사람 골격의 손가락 굽힘을 로봇 손가락에 옮깁니다. 손가락 관절이 없는 모델은 손이 모델 모양 그대로입니다(한 덩어리). AMASS SMPL-X는 손가락을 따르지 않습니다.
  - 결과는 `inspect`·`/api/motion`의 `fingers`에 나옵니다. `rest`는 굽힘 기준입니다: "rest pose"(rest 자세에서 펴진 사람 손가락 마디), "clip"(클립에서 가장 편 값), "mixed"(마디마다 다름: rest 자세에서 굽은 마디만 클립 값). `rest_joints` {rest, clip}는 각 기준을 쓴 마디 수입니다.
  - 로봇 손가락별 결과는 `fingers.fingers.<left|right>.<로봇 손가락>`에 있습니다: `from`(따른 사람 손가락), `joints`, `max_deg`(관절마다 최대 굽힘, 도, 평활화 뒤).
  - `notes`에는 맞는 사람 손가락이 없거나 오므리는 관절을 찾지 못한 경우가 나오고, 따르지 못했으면 `error`가 나옵니다.
  - 손가락 관절은 "관절 한계 걸림"에서, 같은 손 안의 접촉은 "자기 충돌"에서 빠집니다.

- **물체(FBX):** 사람 FBX 안의 물체에 더해, 같은 촬영의 물체만 든 FBX도 함께 그립니다. 예: `Takes_Raw\M1\pick_010_M1.fbx`에 `Prop_Raw\pick_010_Prop.fbx`. 찾는 규칙은 사용 설명서 "따로 받은 물체 FBX"에 있습니다.
  - 요약: 물체 파일은 이름이 `_Prop`(`_Props`, `_Prop2`, `_Prop_1`)로 끝나는 FBX이고, 그 앞이 촬영 이름입니다. 사람 파일 이름 그대로, 없으면 마지막 `_부분`(배우)을 뗀 이름과 맞춥니다.
  - 찾는 곳은 사람 파일 폴더와 위 두 단계, 그 바로 아래의 prop 폴더입니다.
  - prop 폴더 안이나 같은 촬영의 사람 파일 옆에 있는 물체 파일은 모션 목록·일괄 처리에서 빠집니다. `batch`·`export`·`summary`는 다른 곳에 있어도 함께 처리하는 사람 FBX가 쓰는 물체 파일을 뺍니다.
  - 그런 물체 파일은 창이나 `/api/open`으로 열어도 모션으로 열지 않습니다(`/api/open`은 `skipped`에 적고, 그것만 주면 422). 같은 이름의 물체 파일이 여러 폴더에 있으면(`Prop_Raw`, `Prop_Clean`) 사람 쪽 폴더와 이름이 맞는 것(`Takes_Clean` → `Prop_Clean`) 하나만 쓰고, 쓰지 않는 사본은 `skipped`의 why에 "another copy …"로 나옵니다. 그 밖의 물체만 든 FBX를 열면 사람 골격이 아니라는 오류가 납니다.
  - 사람 FBX 안에 작은 골격(관절 8개 미만, 움직임)으로 든 물체(`Ball_1` > `Ball_1:root`)도 `objects[]`에 나옵니다. 골격이 매달린 빈 노드(`reference` 등)는 물체가 아닙니다.
  - `objects[]`에는 따로 받은 물체마다 `file`·`group`(물체 이름)·`parent`(`objects` 안의 위 마디 번호)·`shape`가, `prop_files[]`에는 읽은 파일·쓴 take·`overlap_pct`(모션과 시간 겹침 %)·모양 파일(`shapes`)·오류·쓰지 않은 파일(`skipped`)이 나옵니다. C3D는 솔버 결과의 것이 나옵니다.
  - 이런 파일에는 대개 모양이 없습니다. `shape`는 이렇게 읽습니다.
    - "(기본값)"으로 끝나면 추정한 모양입니다(이름에 ball → 지름 10 cm 구).
    - "(모양 파일)"이면 사용자의 `props.yaml` 모양이고, "파일의 메시"로 시작하면 파일의 메시입니다.
    - `vertices`가 0이면(`shape`가 비었거나 "모양 파일 오류: …") 모양이 없어 원점까지의 거리만 씁니다.
    - 손–물체 수치를 보고할 때는 어느 경우인지 함께 적습니다. `overlap_pct`가 낮으면 물체가 멈춘 채 측정된 것입니다.
  - 실제 모양은 사용자가 `props.yaml`에 적습니다(사용 설명서 "따로 받은 물체 FBX"). 그 파일은 사용자의 데이터이므로 대신 만들거나 고치지 말고, 필요하면 제안만 합니다.

- **구간 라벨:** 모션에 라벨 파일이 있을 수도 없을 수도 있습니다. 열 때 모션 옆의 `<이름>.labels.csv`·`.labels.json`·`_labels.csv`·`_subtask.csv`, 또는 폴더의 `labels.csv`(`seq` 열이 그 모션인 행. 이름이 다르면 같은 촬영 `02_01_stageii` = `02_01`. 이 표에 `seq` 열이 없으면 오류)를 찾습니다. C3D는 솔버 결과 폴더의 라벨도 찾습니다. CSV 열은 `label`(필수), `start_s`·`end_s`(초, 끝 제외) 또는 `start_frame`·`end_frame`(끝 포함, `fps` 열이 없으면 RetLens에 보이는 fps: 리타게팅한 사람 모션은 보통 30이라 원본 프레임 번호면 `fps` 열 필요), 선택 `track`·`name`·`object`·`note`·`color`·`seq`입니다.
  - `inspect`·`/api/motion`의 `labels`가 `null`이면 라벨 파일이 없는 것입니다. 있으면 `file`, `tracks`, `segments[]`(label, start_s, end_s, track), `now`(지금 시각의 라벨), `error`(쓸 수 없는 파일의 이유), `notes`(뺀 행, 잘린 구간)가 나옵니다. `/api/status`에는 `segments`를 뺀 요약만 나옵니다.
  - 라벨 시각은 모션의 첫 프레임 기준입니다. 타임라인 시각은 거기에 시간 오프셋을 더한 값입니다. 어떤 라벨 구간을 보여 주려면 `/api/playback {"time_s": offset_s + start_s}`를 씁니다.
  - **자동 라벨:** 라벨 파일 대신 규칙 파일(YAML·JSON)대로 사람 골격의 동작 트랙(이동·회전·자세·자세전환·왼손·오른손·손·양손·걸음)을 라벨로 바꿉니다. 결과의 `labels.auto`에 규칙 이름이, `file`에 규칙 파일이 나옵니다. 규칙 형식은 사용 설명서 "자동 라벨"과 `retlens/autolabel/rules.py` 머리말에, 트랙 값은 사용 설명서와 `retlens/autolabel/segment.py` 머리말에 있습니다. 예시는 `configs/label_rules_example.yaml`(설치판은 `_internal\configs\`)입니다. 한 표에 같은 항목이 두 번 있거나 `tracks` 옆 맨 위에 레인 항목이 있으면 규칙 오류입니다.
  - 사용자의 규칙 파일은 프로젝트의 라벨 정의라 비공개일 수 있습니다. 그 내용(`label_definitions`의 라벨 이름 포함)을 저장소에 넣거나 밖으로 옮기지 마세요. 로봇 모션(사람 골격 없음)에는 붙지 않습니다. BVH·FBX는 체형을 뼈 길이로 추정해 AMASS SMPL-X보다 덜 정확하고, 발끝 관절이 없는 골격(CMU FBX의 Daz)은 발끝을 추정합니다(`notes`). 트레드밀로 본 구간도 `notes`에 나옵니다.
- **시간 오프셋:** 모션마다 타임라인에서 시작 시각을 옮길 수 있습니다. 비교·RMSE는 겹치는 구간만 봅니다. 같은 촬영의 다른 소스(BVH vs SMPL-X 등)를 비교할 때는 먼저 `align`(또는 `compare --align`)으로 맞추세요.
- **겹쳐 비교:**
  - B를 A의 골반 위치(기본: 골반 방향까지)로 옮겨 자세 차이만 남깁니다. A는 회색 반투명, B는 허용 오차(기본 3 cm)를 넘는 부위만 노랑(1배)→주황(2배)→빨강(3배 이상)으로 칠합니다.
  - 부위 차이는 로봇 부품(G1 30개)의 대표 점들의 평균 거리입니다. 부위(몸통·머리/왼팔/오른팔/왼다리/오른다리) 값은 그 부위에서 가장 많이 벗어난 부품입니다.
  - `heading=false`면 골반 위치만 맞춥니다(향한 방향 차이도 포함).
- **물리 모드:**
  - 각 로봇을 MuJoCo로 시뮬레이션해서, 관절 PD로 클립을 따라가게 합니다(기본 `balance` = `harness`, 클립당 몇 초, 라이선스 동의 불필요).
  - 골반 보조 힘(가상 하네스)은 균형 제어기를 대신합니다. 이 힘에 기대는 비율(`phys_harness_pct`, 체중 %)이 크면 그 동작은 로봇이 혼자 하기 어렵다는 뜻입니다. 보조 힘 모드는 로봇 부위끼리의 충돌을 계산하지 않습니다.
  - MuJoCo의 G1(Unitree 모델)은 Isaac의 G1보다 뒤꿈치 접촉점이 2.5 cm 길고 발 마찰이 커서(1.0 대 미끄러질 때 0.8), 바닥을 스치는 발에서 보조 힘이 Isaac보다 크게 나오고 가끔 Isaac에서는 안 넘어지는 클립이 넘어집니다. 그럴 때는 `--swing-clearance 2`로 다시 보고, 어느 엔진의 결과인지 함께 적습니다.
  - 결과는 캐시되어 다시 요청하면 바로 나옵니다.
  - **균형 제어**(`balance`): `pd`는 같은 MuJoCo에서 보조 힘만 뺀 개루프 재생이라 거의 다 넘어지고, `gmt`는 실제 로봇처럼 추적 정책이 균형을 잡습니다. `isaac`은 같은 보조 힘을 Isaac PhysX로 계산합니다(0.6.0까지의 기본, `assist` 1 = 켬, 0 = 끔). 같은 클립에서 `gmt`도 넘어지거나 `phys_body_error_cm`·토크 한계 초과가 크면 로봇이 따라 하기 어려운 동작입니다. `gmt`는 GMT의 정책 파일이 있어야 합니다. 연구용 라이선스라 프로그램에 넣지 않았고, 사용자가 동의하면 설치 도우미로 받습니다. 정책은 numpy로 계산해서 PyTorch는 필요 없습니다.
- **리타게팅 품질:** 리타게팅이 잘 됐는지를 로봇에 상관없이 같은 기준으로 잽니다(`retlens/retarget_quality.py`). 사람 모션을 열면 계산됩니다.
  - 무엇을 보나: 팔다리가 사람과 같은 쪽을 가리키는지(`pose_err_deg`), 발이 같은 때 바닥에 닿는지(`contact_mismatch_pct`), 로봇 관절이 범위 끝에 걸리는지(`joint_limit_pct`), 로봇 몸끼리 뚫고 지나가는지(`self_collision_pct`).
  - 이 네 지표와 발·균형 지표로 `retarget_score`(0–100)를 냅니다. `inspect`·`/api/motion`의 `retarget_quality`에 부위별 각도, 한계에 붙은 관절, 충돌 부위, 감점 내역이 있습니다.
  - 로봇 모션 파일(npz·csv)만 열면 비교할 사람 모션이 없어서 계산하지 않습니다.
  - **로봇끼리 비교 (저장소 실행에서만, 설치판에는 없음):** `python tools\retarget_benchmark.py --robot A --robot B <클립 폴더>`가 같은 클립을 로봇마다 리타게팅해 `reports\retarget_quality\summary.md`에 로봇별 평균 점수·등급 수·지표 중앙값을 씁니다. 리타게팅 설정(`--foot-flat` 등)을 바꿔 돌리면 설정끼리도 비교할 수 있습니다.
- **리타게팅 보정:** 리타게팅 뒤에 거는 후처리 세 가지입니다. 모두 기본은 끔입니다.
  - **디딤발 평평**(`foot_flat`): 서 있는 발의 발바닥을 바닥에 평평하게 붙입니다. 두 다리 관절과 골반 높이로 맞추고, 움직이는 발과 팔·허리는 그대로 둡니다.
    - CMU 143번처럼 디딤발이 바닥에 평평하지 않아 정적 불균형이 높은 리타겟을 고칠 때 씁니다(143번 BVH·FBX·SMPL-X 0%).
    - 뒤꿈치는 뜨지 않고, 한쪽 발이 떠 있으면 바닥으로 내립니다. 그만큼 골반이 1–3 cm 내려갈 수 있습니다(`foot_flat.root_drop_cm`).
  - 보정과 별개로, T-pose 기준 형식(BVH·FBX·SMPL-X)은 로봇 발이 평평한 기준을 클립에서 사람이 딛고 선 자세로 정합니다(`foot_reference`). 기준 자세의 발 기울기 때문에 생기던 발끝 들림은 대부분 여기서 사라집니다.
  - **스윙 발**(`swing_clearance_cm`): 바닥을 스치는 스윙 발을 띄웁니다.
  - **자기 관통**(`self_collision`): 서로 파고든 로봇 부위를 떼어 놓습니다(손 포함). 팔은 어깨·팔꿈치, 다리는 서 있지 않은 다리의 고관절만 움직이고, 골반·허리·디딤 다리는 그대로입니다. 두 발로 선 채 무릎끼리 닿는 경우는 남고 `self_collision.unresolved_pairs`에 나옵니다.
- **환경:** Isaac Sim, Blender, SMPL-X 모델은 사용자가 설치하고 "환경 설정"에서 지정합니다. 없으면 그 기능만 안 됩니다(`info`의 `checks`가 무엇이 없는지, 어떻게 고치는지 알려 줌).

## 5. 지표 읽는 법

QC(`qc`)는 PASS / WARN / FAIL입니다. 사람 모션의 hard 플래그 프레임이 2% 이하면 PASS, 10% 이하면 WARN, 그 이상이면 FAIL입니다. 판정 이유는 `qc_notes`에 있습니다.

| 키 (`metrics`) | 표 이름 | 뜻 | 보는 법 |
|---|---|---|---|
| `duration` | 길이 (s) | 모션 길이 | |
| `retarget_grade` (`retarget_score`) | 리타게팅 점수 | 0–100점과 등급(85 이상 좋음, 70 이상 보통, 그 밖 나쁨). 사람 모션을 리타게팅한 것만 | 아래 품질 지표와 발 미끄러짐·정적 불균형·바닥 관통이 기준을 넘은 만큼 깎음. 무엇이 깎였는지는 `retarget_quality.score_lost` |
| `pose_err_deg` | 자세 재현 오차 (°) | 허벅지·정강이·위팔·아래팔(좌우)과 몸통(골반 → 양 어깨 가운데)이 사람과 다른 방향을 가리키는 각도 평균 | 로봇 크기·비율과 무관. 8° 이하 좋음, 25° 이상 나쁨. 부위별 값은 `retarget_quality.segments_deg` |
| `contact_mismatch_pct` | 발 접촉 불일치 (%) | 사람과 로봇 중 한쪽 발만 바닥에 닿은 프레임(발마다) | `contact_lost_pct`(사람은 딛는데 로봇 발은 뜸)·`contact_extra_pct`(로봇 발만 붙어 있음)로 나뉨 |
| `joint_limit_pct` | 관절 한계 걸림 (%) | 어느 관절이든(손가락 관절은 뺌) 가동 범위 끝(1° 안)에 붙은 프레임 | 로봇 관절이 동작을 따라갈 만큼 못 돎. 어떤 관절인지는 `retarget_quality.pinned_joints_pct` |
| `self_collision_pct` | 자기 충돌 (%) | 로봇 몸끼리 3 cm 넘게 파고든 프레임(충돌 형상 기준, 같은 손 안끼리는 뺌) | 대개 손이 엉덩이·몸통·다른 손을 뚫음. 부위는 `retarget_quality.collision_pairs_pct`. `--self-collision`으로 다시 봄 |
| `hand_obj_reach_pct` | 물체 닿음 재현 (%) | FBX에 물체가 있을 때만(C3D는 솔버 결과의 물체). 사람 손(손바닥 가운데나 손가락 뿌리 중 하나)이 물체 표면 6 cm 안인 프레임 중 로봇 같은 손(손바닥 점: 손가락 관절이 있으면 손 몸체와 손가락 뿌리의 가운데, 없으면 손 몸체)도 닿은 비율. 로봇 손은 6 cm + 사람의 손바닥 여유(사람 손바닥 점이 물체에 가장 가까운 손 점보다 물체에서 더 먼 만큼, 로봇 크기에 맞춤) 안이면 닿음. 손바닥으로 쥐면 여유 0, 손가락으로 쥔 공은 그만큼 더 | 낮으면 리타겟된 손이 물체를 못 잡음(팔 길이·비율). 물체별은 `objects[]`(contact_s, robot_distance_cm) |
| `hand_obj_err_cm` | 손–물체 거리 (cm) | 같은 프레임들에서 로봇 손바닥 점–물체 표면 평균 거리(여유를 빼지 않은 값) | 물체 위치는 사람 스켈레톤처럼 로봇 크기로 옮긴 근삿값, 크기는 실제 그대로 |
| `acc_mean` | 관절 가속도 (rad/s²) | 관절 각가속도 크기 평균 | 같은 동작끼리 비교. 클수록 떨림 |
| `jerk_mean` | 관절 저크 (rad/s³) | 각가속도 변화율 평균 | 떨림에 가장 민감 |
| `vel_max` | 최대 관절속도 (rad/s) | 가장 빠른 관절 속도 | 모터 한계(대략 20–30 rad/s) 근처면 의심 |
| `planted_slip_pct` | 발 미끄러짐 (%) | 발바닥이 붙은 채 0.3 m/s 이상으로 0.1 s 넘게 움직인 프레임 | 깨끗한 클립은 0–5% |
| `penetration_pct` | 바닥 관통 (%) | 발 최저점이 바닥 아래 2 cm보다 깊은 프레임 | 0이 정상 |
| `sole_min_cm` | 발 최저점 (cm) | 가장 낮게 내려간 발 높이 | 음수 = 바닥 아래 |
| `swing_low_pct` | 스윙 발 바닥 근접 (%) | 움직이는 발이 바닥 1 cm 안을 지나는 비율 | 높으면 물리에서 발끝이 걸려 넘어지기 쉬움 |
| `com_out_pct` | CoM 지지 밖 (%) | CoM 투영이 지지다각형 밖인 비율 | 걷기에선 정상 동작도 높음 |
| `zmp_out_pct` | ZMP 지지 밖 (%) | ZMP가 지지다각형 밖인 비율 | |
| `static_unbalanced_pct` | 정적 불균형 (%) | 거의 멈춘 채 CoM이 발 밖 2 cm 넘게 0.2 s 이상 | 5% 넘으면 QC WARN, 로봇이 설 수 없는 자세. 디딤발이 평평하지 않은 리타겟이면 `--foot-flat`으로 다시 봄 |
| (표만) | 기준 대비 다리 / 전체 RMSE (°) | 기준과 겹치는 구간의 관절별 RMSE 중앙값 | 같은 촬영의 다른 소스끼리 몇 도 이내면 일치 |
| `phys_harness_pct` | 물리: 보조 힘 (체중 %) | 골반 보조 힘 평균(MuJoCo 없음·GMT는 0) | 클수록 로봇 혼자 균형 잡기 어려움 |
| `phys_falls` | 물리: 넘어짐 | 넘어진 횟수 | 0이 목표. `physics.falls[]`에 시각과 1차 원인(MuJoCo·Isaac 모두, `cause_id`), MuJoCo는 넘어짐 판정 기준(`rule`)도 |
| `phys_fall_causes` | 물리: 넘어짐 원인 | 1차 원인별 횟수, 많은 순(같으면 발끝 걸림·발 미끄러짐·자기충돌 근접·토크 포화·지지면 이탈·보조 힘 급증 순. 예: `지지면 이탈 7 · 발끝 걸림 1 · 토크 포화 1`, Isaac은 앞 20회만이면 `(앞 20회)`) | 넘어짐 직전 0.75초에 먼저 시작된 조건. `toe_catch`(발끝 걸림) → 스윙 발 보정, `support_exit`(지지면 이탈)이고 `evidence.clip_com_margin_cm` < 0이면 원본 자체가 불균형(디딤발 평평 보정·`static_unbalanced_pct`), `self_collision` → 자기 관통 보정, `torque_saturation` → `evidence.joint`, `foot_slip` → `planted_slip_pct`. GMT에서는 정책이 발을 일부러 디디고 있어도 발끝 걸림으로 나올 수 있음 |
| `phys_body_error_cm` | 물리: 몸 위치 오차 (cm) | MuJoCo 결과만: 골반 기준 몸통·무릎·발목·팔꿈치·손 위치가 원본과 다른 평균 | CMU 17클립에서 GMT 3–7 cm, 제어기 없음 7–11 cm |
| `phys_saturated_pct` | 물리: 토크 한계 초과 (%) | 관절 토크가 모터 한계를 넘은 프레임 | |
| `phys_torque_limits_missing` | (분석 표에 없음) | G1이 아닌 로봇의 MuJoCo 결과만: 토크 한계가 없는 관절 수(결과 json의 `torque_limits_missing`) | 그 관절은 1000 N·m로 두어 토크 포화를 판정하지 않음. 그만큼 `phys_saturated_pct`·토크 포화 원인이 덜 나옴. 창의 물리 결과 줄 끝에 "토크 한계 없는 관절 n개(토크 포화 판정 안 함)" |
| `phys_ok` | 물리 판정 | "통과" 또는 걸린 기준 | 넘어짐 없음, 보조 힘 > 체중 20% 프레임 5% 이하, 토크 초과 5% 이하 |

`ik_position_residual`은 리타게팅 IK가 목표 위치를 못 맞춘 정도(cm, pelvis/feet/hands)입니다. 손은 로봇 팔이 짧아 10 cm 안팎도 흔합니다. `c3d`는 원본 마커 QC입니다(빠짐 %, 가장 긴 공백, 튐 = 두 샘플 사이 10 m/s 넘는 이동, 마커 라벨 뒤바뀜이나 유령 점).

## 6. 자주 하는 작업

1. **폴더의 클립들 품질 보기:** `library --query ...` → `inspect` 여러 개 → `qc`가 FAIL/WARN인 것과 `qc_notes`, `retarget_score`가 낮은 것과 그 `retarget_quality.score_lost`, 눈에 띄는 지표(발 미끄러짐, 관통, 스윙 발 바닥 근접, 정적 불균형)를 정리합니다. 여러 클립·로봇을 한 표로 보려면 저장소의 `tools\retarget_benchmark.py`를 씁니다(설치판에서는 `inspect` 결과를 모아 표로 만듭니다).
2. **같은 촬영의 두 소스 비교(예: CMU 02_01 BVH vs AMASS SMPL-X):**
   - `compare A B --align`으로 부위별 평균·최대와 `worst_moments`를 받습니다.
   - 창이 떠 있으면 `/api/open` → `/api/align` → `/api/compare` → `/api/playback {"time_s": <worst>}` → `/api/screenshot`으로 그 순간을 보여 줍니다.
3. **로봇이 실제로 할 수 있는 동작인지:** `physics FILE`(기본 MuJoCo 보조 힘, 클립당 몇 초, 동의 필요 없음. `--balance isaac`은 EULA 동의가 필요하고 약 1분) → `phys_ok`, `phys_fall_causes`, `falls[].cause_id`와 `evidence`(예: `toe_catch` 발끝 걸림)를 보고, 원인이 스윙 발이면 `retarget --swing-clearance 2.5`로 다시 만들어 비교합니다.
4. **서 있는데 균형이 안 맞는 클립(`static_unbalanced_pct`가 높음):**
   - `inspect FILE`과 `inspect FILE --foot-flat`을 비교합니다. 보정으로 정적 불균형이 내려가면, 원인은 디딤발이 바닥에 평평하게 붙지 않던 리타겟입니다. `foot_flat.stance_tilt_deg`(디딤발 기울기 전→후)와 두 발 높이차(`foot_flat.two_feet_height_diff_cm`)로 확인합니다. 기준 자세가 이미 발 pitch를 맞추므로 `stance_pitch_deg`는 크게 바뀌지 않을 수 있습니다. 골반을 낮춘 높이(`foot_flat.root_drop_cm`)와 `swing_low_pct` 변화도 함께 보고합니다.
   - 창이 떠 있으면 `/api/open`(보정 전) → `/api/retarget {"foot_flat": true}` → 같은 파일을 `/api/open`하면 전후가 나란히 보입니다. 끝나면 `/api/retarget {"foot_flat": false}`로 되돌립니다.
5. **C3D 원본 품질:** `c3d-qc` → 빠짐·공백·튐이 큰 마커를 보고합니다. `inspect file.c3d`면 솔버 스켈레톤과의 정렬 잔차(`c3d.residual_cm`)도 나옵니다.
6. **결과 파일 만들기:** `retarget FILE --out out.npz`. 권장 설정은 `--swing-clearance 2`이고, 정적 불균형이 높고 `--foot-flat`으로 내려가는 클립이면 `--foot-flat`도 붙입니다. 그다음 `inspect out.npz`로 확인합니다.

## 7. 지킬 것

- **설치 도우미(`setup`)로 무언가를 설치하기 전에는 사용자에게 먼저 묻습니다.** 무엇을, 어디서, 얼마나 받는지(`download`)를 말합니다.
  - `action`이 `none`이면 이미 있으니 설치하지 않습니다.
  - `configure`면 이미 이 PC에 있는 호환 버전(`target`)으로 환경 설정만 바꿉니다. 아무것도 받지 않지만 설정이 바뀌므로 그 경로를 알리고 묻습니다.
  - Isaac은 기존 폴더를 덮어쓰지 않습니다. `C:\isaacsim`이 차 있으면 `C:\isaacsim-6.1.0`에 설치합니다(`download`에 나옴).
  - `blocked`면 `note`의 이유(예: RTX GPU 없음, 디스크 부족)를 그대로 전합니다.
  - `manual`(SMPL-X)은 사용자가 사이트에서 등록하고 받아야 합니다. 대신 받지 않습니다.
  - `--accept-license`는 사용자가 그 라이선스(GMT 연구용, NVIDIA EULA)에 직접 동의했다고 말했을 때만 붙입니다.
- **Isaac Sim 라이선스(NVIDIA Omniverse EULA)는 사용자만 동의할 수 있습니다.**
  - `isaac_eula_accepted`가 false면 Isaac 물리(`balance` `isaac`)·녹화를 하지 말고, 사용자에게 RetLens 창에서 균형 제어 "보조 힘 (Isaac)"을 한 번 골라 동의해 달라고 하세요. MuJoCo 물리는 동의가 필요 없습니다.
  - `--isaac-accept-eula`는 사용자가 직접 동의했다고 말했을 때만 씁니다.
- **라이선스 제한 데이터는 배포·공유하지 마세요:** SMPL-X 모델 파일, AMASS, LAFAN1, Unitree LAFAN1 리타겟과 그 파생물(리타겟 npz·동영상 포함)이 해당합니다. CMU 데이터는 공개해도 됩니다.
- **Isaac 물리·녹화는 오래 걸립니다(클립당 수십 초에서 몇 분, MuJoCo 물리는 몇 초).** 여러 개면 사용자에게 먼저 알리고, `/api/jobs`로 진행을 봅니다. 같은 요청을 반복해서 보내지 마세요(캐시와 대기열이 처리함).
- 사용자의 캐시(`cache\`), 설정 파일, 원본 데이터를 지우거나 바꾸지 마세요.
- **사용자가 고친 라벨은 사용자의 작업입니다.** 저장하지 않은 편집(`labels.unsaved_edits`)을 `discard_edits`로 버리거나, 있는 라벨 파일에 `overwrite`로 덮어쓰거나, 작업 세션을 `discard_changes`로 닫고 열기는 사용자가 그렇게 하라고 했을 때만 합니다. 저장은 사용자가 말한 경로에만 합니다.
- 새 소프트웨어나 데이터를 내려받거나 설치하기 전에는 출처와 크기를 말하고 물어보세요.
- 숫자를 보고할 때는 어떤 모션(라벨), 어떤 기준(ref), 어떤 설정(허용 오차, heading, assist, 리타게팅 보정)이었는지 함께 적으세요.
- 창의 리타게팅 보정을 바꿨으면 작업이 끝난 뒤 원래대로 돌려 놓으세요. 사용자가 다음에 여는 모션에도 적용되기 때문입니다.

## 8. 문제 해결

| 증상 | 확인 |
|---|---|
| `retlens-cli api`가 오류 | RetLens 창이 안 떠 있거나 API가 꺼짐. 사용자에게 창을 띄워 달라고 하거나 명령줄로 처리 |
| 401 | 토큰이 틀림. 창을 다시 켜면 바뀌므로 `api.json`을 다시 읽음 |
| FBX·SMPL-X를 못 엶 | `info`의 `checks`(blender / smpl), `setup`. 사용자가 환경 설정이나 설치 도우미에서 지정·설치 |
| 균형 제어 GMT "설치 필요" | `setup`의 `gmt`. 연구용 라이선스에 사용자가 동의하면 설치 도우미(또는 `setup --install gmt --accept-license`)로 받음. PyTorch는 필요 없음 |
| 물리 "실행할 수 없음" | Isaac(`balance` `isaac`, 녹화)이면 Isaac Sim 경로(`checks.isaac`)와 라이선스 동의 확인. 로봇 USD는 기본으로 NVIDIA 에셋 서버에서 받으므로 인터넷이 필요. MuJoCo면 G1 모델(설치판에 들어 있음, 저장소는 `..\GMT`). G1이 아닌 로봇이면 harness / pd는 그 로봇의 모델로 돌고(G1 게인 × 로봇 질량 / G1 질량; 결과 json의 `model`에 적힘), gmt는 G1 전용, isaac은 그 로봇의 USD(환경 설정 > 로봇 USD)가 있어야 됩니다. 토크 한계는 관절 자체의 한계(`actuatorfrcrange`, URDF `effort`)가 먼저이고, 없을 때만 모터의 한계(`forcerange` × `gear`, 또는 모터의 `ctrlrange` × `gain` × `gear`, 둘 다 있으면 작은 값)를 씁니다. -1..1로 정규화된 명령(`gain` × `gear` ≤ 1)은 토크가 아니라 보지 않습니다. 둘 다 없는 관절은 1000 N·m로 두어 토크 포화를 판정하지 않습니다. 그 수는 결과의 `torque_limits_missing`, 지표 `phys_torque_limits_missing`(`batch` 행에도), 로봇 `notes`("torque limits missing on N joints", `robot`·`/api/status`)에 나옵니다. 물리는 2프레임 이상, fps가 0보다 큰 모션만 됩니다 |
| 비교 `frames: 0` | 두 모션이 같이 재생되는 구간이 없음. 오프셋을 확인하거나 `--align` |

자세한 설명은 사용 설명서(설치판: 설치 폴더의 `_internal\docs\manual.md`, 저장소: `docs/manual.md`)에, 지표 정의는 `metrics` 결과의 설명(저장소: `retlens/app/scene.py`의 `METRIC_HELP`)에 있습니다.
