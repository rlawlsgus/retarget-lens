---
name: retlens
description: Drive RetLens (Retarget Lens), the tool that retargets human mocap (BVH, FBX, AMASS SMPL-X, C3D markers) to the Unitree G1 robot and validates it - QC, smoothness / foot / balance metrics, overlay comparison of two motions, Isaac Sim physics checks and videos. Use it when the user asks to retarget or check mocap, compare motions or capture sources, find what is wrong with a clip, run a physics check, inspect C3D marker quality, or show / operate something in the open RetLens window. Commands give JSON; a running window has a local HTTP API.
---

# RetLens로 일하기 (AI용 안내)

RetLens는 사람 모션캡처를 휴머노이드 로봇(지금은 Unitree G1)으로 옮기고(리타게팅, GMR) 그 결과를 검증하는 데스크톱 프로그램입니다. AI는 두 가지 방법으로 다룹니다.

| 방법 | 언제 | 무엇 |
|---|---|---|
| **명령줄 `retlens-cli`** | 창 없이 계산만 할 때, 여러 파일을 한꺼번에 볼 때 | 리타게팅, QC·지표, 겹쳐 비교 수치, 시간 정렬, C3D 마커 QC, Isaac 물리·녹화. 결과는 JSON 한 덩어리 |
| **로컬 HTTP API** | 사용자가 RetLens 창을 띄워 두었고, 화면에서 무언가를 보여 주거나 조작할 때 | 모션 열기, 재생·탐색, 겹쳐 비교 켜기, 물리 모드, 지표, 스크린샷 |

두 방법 모두 창과 같은 코드(`retlens/app/scene.py`의 MotionScene)를 써서 숫자가 화면과 같습니다.

## 1. 실행 방법 찾기

- **저장소(개발)에서:** `conda run -n retlens python tools\retlens_cli.py <명령> ...` (저장소 루트에서). 창은 `scripts\editor.bat`.
- **설치판:** 설치 폴더의 `retlens-cli.exe <명령> ...`(`RetLens.exe` 옆).
- 먼저 `retlens-cli info`로 환경을 확인하세요. 파일 위치, 각 기능에 필요한 외부 프로그램(Isaac Sim, Blender, SMPL-X 모델)이 있는지(`checks`), Isaac 라이선스 동의 여부(`isaac_eula_accepted`)가 나옵니다.
- 출력은 stdout의 JSON 한 줄입니다(`--pretty`면 들여쓰기). 진행 메시지는 stderr로 나옵니다. 실패하면 종료 코드가 1이고 `{"error": "..."}`를 출력합니다.

## 2. 명령줄 `retlens-cli`

| 명령 | 하는 일 | 주요 출력 |
|---|---|---|
| `info` | 버전, 파일 위치, 환경 점검 | `locations`, `checks[]`(key, ok, needed_for, hint), `isaac_eula_accepted` |
| `library [--query Q] [--limit N]` | 모션 폴더의 파일 목록. Q는 파일 이름과 CMU 동작 설명에서 찾음(예: `143_11`, `walk`, `dance`) | `files[]`(path, folder, name, cmu_description) |
| `inspect FILE...` | 열고(필요하면 리타게팅, 캐시) 모션 하나하나의 정보 | `motions[]`(id, kind, frames, fps, duration_s, qc, qc_notes, ik_position_residual, retarget, foot_flat, foot_reference, self_collision, metrics, retarget_quality, c3d) |
| `metrics FILE... [--ref N]` | 창의 "분석" 표와 같은 표. 기준(ref, 기본은 첫 파일) 대비 RMSE 포함 | `rows`, `motions[].values`, `row_help` |
| `compare A B [--tol 3] [--no-heading] [--align]` | 겹쳐 비교: B를 A의 골반에 맞춰 부위별 차이(cm) | `regions[]`(region, mean_cm, max_cm, max_at_s, beyond_tol_pct), `worst_moments[]` |
| `align REF FILE...` | 기준에 시간 자동 정렬(다리 관절각이 가장 잘 맞는 오프셋) | `offsets_s`, `notes` |
| `retarget FILE --out OUT.npz [--smooth 6] [--foot-flat] [--swing-clearance CM] [--self-collision]` | 리타게팅해서 로봇 모션 npz(+ json)로 저장 | `out`, `frames`, `fps`, `kind` |
| `autolabel FILE... [--rules R.yaml] [--out DIR] [--summary]` | 자동 라벨: 규칙 파일대로 사람 동작을 보고 구간 라벨(리타게팅 없이). `--out`이면 모션마다 `<이름>.labels.csv`(이름이 겹치면 원래 폴더 구조를 그 아래에 둠) | `rules`, `motions[]`(file, labels{auto, tracks, segments[], notes, error}, csv) |
| `c3d-qc FILE.c3d...` | C3D 원본 마커 QC만(리타게팅 없이) | 마커 수, `missing_pct`, `most_missing`, `longest_gap_s`, `spike_frames` |
| `physics FILE [--assist 1]` | Isaac PhysX 물리 검사(짧은 클립 약 1분) | `physics.metrics`(phys_falls, phys_harness_pct, phys_saturated_pct, phys_ok), `physics.falls[]` |
| `video FILE [--out X.mp4] [--physics]` | Isaac으로 녹화 | `video` 경로 |
| `setup [--offline]` | 설치 도우미 점검: Blender·GMT·Isaac Sim·SMPL-X가 이 PC에 있는지, 없으면 설치할 수 있는지(GPU·드라이버·디스크·인터넷·쓰기 권한) | `components[]`(key, state, action, found, detail, note, requirements[], license) |
| `setup --install KEY [--accept-license] [--source ZIP]` | 그 구성 요소를 필요할 때만 설치. 이미 호환되는 것이 있으면 아무것도 받지 않음 | 설치 뒤 상태 |
| `api` | 떠 있는 창의 HTTP API 주소와 토큰 | `url`, `token` |
| `install-skill [--project DIR]` | 이 안내를 Claude Code 스킬 폴더에 복사 | `installed` |

- **모션 파일:**
  - 사람 모션: BVH, FBX(Blender 필요), AMASS SMPL-X `*_stageii.npz`(SMPL-X 모델 필요), C3D.
  - 로봇 모션: npz, Unitree csv, GMR pkl.
  - 사람 모션은 처음 열 때 리타게팅합니다. 처음에는 몇 초에서 수십 초가 걸리고, 다음부터는 캐시에서 바로 나옵니다.
- **리타게팅 보정:** 모션을 여는 명령(`inspect`, `metrics`, `compare`, `align`, `retarget`, `physics`, `video`)은 사람 모션을 어떻게 리타게팅할지 정하는 옵션을 받습니다. 로봇 모션은 그대로 엽니다.
  - `--smooth HZ`: 평활화(기본 6, 0 = 끔).
  - `--foot-flat`: 디딤발 평평 보정.
  - `--swing-clearance CM`: 스윙 발 보정(권장 2).
  - `--self-collision`: 자기 관통 보정. 바꾼 내용은 `self_collision`(바뀐 프레임 수, 3 cm 넘게 파고든 프레임 전→후, 가장 깊은 곳 전→후, 남은 부위 쌍과 그 프레임 수 `unresolved_pairs`)에 있습니다.
  - 설정마다 캐시가 따로 있어서 보정 전후를 각각 열 수 있습니다. 어떤 설정으로 만들었는지는 `retarget`(smooth_hz, foot_flat, swing_clearance_cm, self_collision)에 나옵니다. 디딤발 평평 보정이 바꾼 내용은 `foot_flat`(바뀐 프레임 수, 디딤 중 발 pitch·기울기 전→후, 골반을 낮춘 높이 `root_drop_cm`, 두 발 높이차 `two_feet_height_diff_cm`)에 있습니다.
- **C3D:** 마커만으로는 로봇을 움직일 수 없습니다. 같은 이름의 솔버 결과(BVH → FBX → AMASS 순)를 찾아 그것을 리타게팅하고, 마커를 옆에 그립니다. 없으면 오류가 납니다.

## 3. 로컬 HTTP API (떠 있는 RetLens 창)

- 창이 떠 있으면 `127.0.0.1`의 기본 포트 8765에서 동작합니다(사용자가 "환경 설정 > AI 연동"에서 끌 수 있음).
- **주소와 토큰:** `retlens-cli api`, 또는 사용자 데이터 폴더의 `api.json`에서 읽습니다(설치판 `%LOCALAPPDATA%\RetLens\api.json`, 저장소 `data\api.json`). 토큰은 창을 켤 때마다 바뀝니다.
- 모든 요청에 `Authorization: Bearer <token>` 헤더가 있어야 합니다. 웹 페이지의 요청(`Origin` 헤더)은 거부합니다.
- 응답은 `{"ok": true, ...}` 또는 `{"ok": false, "error": "..."}`이고, 오류면 HTTP 코드도 4xx/5xx입니다.

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
| `GET /api/status` | 시각, 재생 상태, 물리 모드, 겹쳐 비교, 열린 모션 |
| `GET /api/checks` | 환경 점검 |
| `GET /api/library?query=walk` | 모션 파일 목록 |
| `POST /api/open {"paths": [...]}` | 열기(창에 나타나고 선택됨) |
| `POST /api/retarget {"foot_flat"?, "swing_clearance_cm"?, "self_collision"?}` | 리타게팅 보정(창의 "리타게팅" 메뉴). 다음에 여는 사람 모션부터 적용되고, 이미 연 모션은 그대로입니다. 지금 설정은 `/api/status`의 `retarget` |
| `POST /api/remove {"id"}` | 닫기 |
| `GET /api/motion?id=...` | 모션 하나의 QC·지표·C3D·물리·구간 라벨 |
| `POST /api/item {"id", "visible"?, "offset_s"?, "show_human"?}` | 보이기, 시간 오프셋, 사람 스켈레톤 |
| `POST /api/labels {"id", "path"?}` | 구간 라벨: `path` 파일을 붙임 / `"path": null`이면 뺌 / `path`가 없으면 라벨 파일을 다시 읽음 |
| `POST /api/labels {"id", "auto": true, "rules"?}` | 자동 라벨: 규칙 파일(`rules`, 없으면 사용자가 고른 설정)대로 붙임. 붙일 수 없으면(로봇 모션, 깨진 규칙) 422이고 라벨은 그대로 |
| `POST /api/playback {"play"?, "time_s"?, "speed"?, "loop"?}` | 재생/정지, 시각 이동 |
| `GET /api/metrics?ref=...` | 분석 표 |
| `POST /api/align {"ref"}` | 시간 자동 정렬 |
| `POST /api/compare {"a", "b", "heading"?, "tol_cm"?}` / `{"on": false}` | 겹쳐 비교를 켜고 수치 받기 / 끄기 |
| `POST /api/physics {"on", "assist"?, "balance"?}` | 물리 모드. `balance`: `isaac`(보조 힘, 기본) / `pd`(MuJoCo 제어기 없음) / `gmt`(MuJoCo GMT 추적 정책). 결과는 `/api/jobs`·`/api/motion`으로 확인 |
| `POST /api/video {"id"}` | 동영상 저장(대기열) |
| `GET /api/jobs` | 물리(Isaac·MuJoCo)·동영상 작업 상태와 결과 경로 |
| `POST /api/camera {"fit": true}` | 카메라 맞추기 |
| `POST /api/screenshot {"path"?}` | 창 스크린샷 PNG(경로를 돌려줌, 이미지로 읽어 확인 가능) |

- `id`는 모션 라벨(`"cmu_bvh/02_01"` 처럼 폴더/파일 이름, 한 장면에서 유일)입니다. 순서 번호(0부터)나 파일 이름도 됩니다.

## 4. 알아야 할 개념

- **구간 라벨:** 모션에 라벨 파일이 있을 수도 없을 수도 있습니다. 열 때 모션 옆의 `<이름>.labels.csv`·`.labels.json`·`_labels.csv`·`_subtask.csv`, 또는 폴더의 `labels.csv`(`seq` 열이 그 모션인 행. 이름이 다르면 같은 촬영 `02_01_stageii` = `02_01`. 이 표에 `seq` 열이 없으면 오류)를 찾습니다. C3D는 솔버 결과 폴더의 라벨도 찾습니다. CSV 열은 `label`(필수), `start_s`·`end_s`(초, 끝 제외) 또는 `start_frame`·`end_frame`(끝 포함, `fps` 열이 없으면 RetLens에 보이는 fps: 리타게팅한 사람 모션은 보통 30이라 원본 프레임 번호면 `fps` 열 필요), 선택 `track`·`name`·`object`·`note`·`color`·`seq`입니다.
  - `inspect`·`/api/motion`의 `labels`가 `null`이면 라벨 파일이 없는 것입니다. 있으면 `file`, `tracks`, `segments[]`(label, start_s, end_s, track), `now`(지금 시각의 라벨), `error`(쓸 수 없는 파일의 이유), `notes`(뺀 행, 잘린 구간)가 나옵니다. `/api/status`에는 `segments`를 뺀 요약만 나옵니다.
  - 라벨 시각은 모션의 첫 프레임 기준입니다. 타임라인 시각은 거기에 시간 오프셋을 더한 값입니다. 어떤 라벨 구간을 보여 주려면 `/api/playback {"time_s": offset_s + start_s}`를 씁니다.
  - **자동 라벨:** 라벨 파일 대신 규칙 파일(YAML·JSON)대로 사람 골격의 동작 트랙(이동·자세·자세전환·왼손·오른손·손·양손·걸음)을 라벨로 바꿉니다. 결과의 `labels.auto`에 규칙 이름이, `file`에 규칙 파일이 나옵니다. 규칙 형식과 트랙 값은 사용 설명서 "자동 라벨"과 `retlens/autolabel/rules.py` 머리말에 있습니다. 예시는 `configs/label_rules_example.yaml`입니다.
  - 사용자의 규칙 파일은 프로젝트의 라벨 정의라 비공개일 수 있습니다. 그 내용을 저장소에 넣거나 밖으로 옮기지 마세요. 로봇 모션(사람 골격 없음)에는 붙지 않습니다. BVH·FBX는 체형을 뼈 길이로 추정해 AMASS SMPL-X보다 덜 정확합니다(`notes`).
- **시간 오프셋:** 모션마다 타임라인에서 시작 시각을 옮길 수 있습니다. 비교·RMSE는 겹치는 구간만 봅니다. 같은 촬영의 다른 소스(BVH vs SMPL-X 등)를 비교할 때는 먼저 `align`(또는 `compare --align`)으로 맞추세요.
- **겹쳐 비교:**
  - B를 A의 골반 위치(기본: 골반 방향까지)로 옮겨 자세 차이만 남깁니다. A는 회색 반투명, B는 허용 오차(기본 3 cm)를 넘는 부위만 노랑(1배)→주황(2배)→빨강(3배 이상)으로 칠합니다.
  - 부위 차이는 로봇 부품(G1 30개)의 대표 점들의 평균 거리입니다. 부위(몸통·머리/왼팔/오른팔/왼다리/오른다리) 값은 그 부위에서 가장 많이 벗어난 부품입니다.
  - `heading=false`면 골반 위치만 맞춥니다(향한 방향 차이도 포함).
- **물리 모드:**
  - 각 로봇을 Isaac Sim PhysX로 시뮬레이션해서, 관절 PD로 클립을 따라가게 합니다.
  - 골반 보조 힘(`assist` 1 = 기본, 0 = 끔)은 균형 제어기를 대신합니다. 이 힘에 기대는 비율이 크면 그 동작은 로봇이 혼자 하기 어렵다는 뜻입니다.
  - 결과는 캐시되어 다시 요청하면 바로 나옵니다.
  - **균형 제어**(`balance`)를 `pd`/`gmt`로 바꾸면 Isaac 대신 MuJoCo로 계산합니다(클립당 몇 초, 라이선스 동의 불필요). `pd`는 제어기 없는 개루프 재생이라 거의 다 넘어지고, `gmt`는 실제 로봇처럼 추적 정책이 균형을 잡습니다. 같은 클립에서 `gmt`도 넘어지거나 `phys_body_error_cm`·토크 한계 초과가 크면 로봇이 따라 하기 어려운 동작입니다. `gmt`는 GMT의 정책 파일이 있어야 합니다. 연구용 라이선스라 프로그램에 넣지 않았고, 사용자가 동의하면 설치 도우미로 받습니다. 정책은 numpy로 계산해서 PyTorch는 필요 없습니다.
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
| `joint_limit_pct` | 관절 한계 걸림 (%) | 어느 관절이든 가동 범위 끝(1° 안)에 붙은 프레임 | 로봇 관절이 동작을 따라갈 만큼 못 돎. 어떤 관절인지는 `retarget_quality.pinned_joints_pct` |
| `self_collision_pct` | 자기 충돌 (%) | 로봇 몸끼리 3 cm 넘게 파고든 프레임(충돌 형상 기준) | 대개 손이 엉덩이·몸통·다른 손을 뚫음. 부위는 `retarget_quality.collision_pairs_pct`. `--self-collision`으로 다시 봄 |
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
| `phys_harness_pct` | 물리: 보조 힘 (체중 %) | 골반 보조 힘 평균(MuJoCo는 0) | 클수록 로봇 혼자 균형 잡기 어려움 |
| `phys_falls` | 물리: 넘어짐 | 넘어진 횟수 | 0이 목표. `physics.falls[]`에 시각과 1차 원인(MuJoCo는 넘어짐 판정 기준) |
| `phys_body_error_cm` | 물리: 몸 위치 오차 (cm) | MuJoCo 결과만: 골반 기준 몸통·무릎·발목·팔꿈치·손 위치가 원본과 다른 평균 | CMU 17클립에서 GMT 3–7 cm, 제어기 없음 7–11 cm |
| `phys_saturated_pct` | 물리: 토크 한계 초과 (%) | 관절 토크가 모터 한계를 넘은 프레임 | |
| `phys_ok` | 물리 판정 | "통과" 또는 걸린 기준 | 넘어짐 없음, 보조 힘 > 체중 20% 프레임 5% 이하, 토크 초과 5% 이하 |

`ik_position_residual`은 리타게팅 IK가 목표 위치를 못 맞춘 정도(cm, pelvis/feet/hands)입니다. 손은 로봇 팔이 짧아 10 cm 안팎도 흔합니다. `c3d`는 원본 마커 QC입니다(빠짐 %, 가장 긴 공백, 튐 = 두 샘플 사이 10 m/s 넘는 이동, 마커 라벨 뒤바뀜이나 유령 점).

## 6. 자주 하는 작업

1. **폴더의 클립들 품질 보기:** `library --query ...` → `inspect` 여러 개 → `qc`가 FAIL/WARN인 것과 `qc_notes`, `retarget_score`가 낮은 것과 그 `retarget_quality.score_lost`, 눈에 띄는 지표(발 미끄러짐, 관통, 스윙 발 바닥 근접, 정적 불균형)를 정리합니다. 여러 클립·로봇을 한 표로 보려면 저장소의 `tools\retarget_benchmark.py`를 씁니다(설치판에서는 `inspect` 결과를 모아 표로 만듭니다).
2. **같은 촬영의 두 소스 비교(예: CMU 02_01 BVH vs AMASS SMPL-X):**
   - `compare A B --align`으로 부위별 평균·최대와 `worst_moments`를 받습니다.
   - 창이 떠 있으면 `/api/open` → `/api/align` → `/api/compare` → `/api/playback {"time_s": <worst>}` → `/api/screenshot`으로 그 순간을 보여 줍니다.
3. **로봇이 실제로 할 수 있는 동작인지:** `physics FILE`(라이선스 동의 필요, 약 1분) → `phys_ok`, `falls[].cause`(예: 발끝 걸림)를 보고, 원인이 스윙 발이면 `retarget --swing-clearance 2.5`로 다시 만들어 비교합니다.
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
  - `isaac_eula_accepted`가 false면 물리·녹화를 하지 말고, 사용자에게 RetLens 창에서 물리 모드를 한 번 켜서 동의해 달라고 하세요.
  - `--isaac-accept-eula`는 사용자가 직접 동의했다고 말했을 때만 씁니다.
- **라이선스 제한 데이터는 배포·공유하지 마세요:** SMPL-X 모델 파일, AMASS, LAFAN1, Unitree LAFAN1 리타겟과 그 파생물(리타겟 npz·동영상 포함)이 해당합니다. CMU 데이터는 공개해도 됩니다.
- **물리·녹화는 오래 걸립니다(클립당 수십 초에서 몇 분).** 여러 개면 사용자에게 먼저 알리고, `/api/jobs`로 진행을 봅니다. 같은 요청을 반복해서 보내지 마세요(캐시와 대기열이 처리함).
- 사용자의 캐시(`cache\`), 설정 파일, 원본 데이터를 지우거나 바꾸지 마세요.
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
| 물리 "실행할 수 없음" | Isaac Sim 경로(`checks.isaac`)와 라이선스 동의 확인. 로봇 USD는 기본으로 NVIDIA 에셋 서버에서 받으므로 인터넷이 필요 |
| 비교 `frames: 0` | 두 모션이 같이 재생되는 구간이 없음. 오프셋을 확인하거나 `--align` |

자세한 설명은 사용 설명서(설치판: 설치 폴더의 `_internal\docs\manual.md`, 저장소: `docs/manual.md`)에, 지표 정의는 `metrics` 결과의 설명(저장소: `retlens/app/scene.py`의 `METRIC_HELP`)에 있습니다.
