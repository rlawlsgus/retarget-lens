# K-Humanoid — RetLens와 모캡 데이터셋 도구

K-온디바이스 휴머노이드 과제 1차년도 산출물인 **Human MoCap 기반 전신 모션 데이터셋**을 모으고 검증하기 위한 저장소입니다. 중심은 데스크톱 프로그램 **RetLens**(Retarget Lens)이고, 같은 코어를 쓰는 명령줄 도구가 함께 있습니다.

- **리타게팅:** 사람 모캡(BVH, FBX, AMASS SMPL-X, C3D)을 GMR IK로 Unitree G1(29 DoF)에 옮깁니다. LG 휴머노이드 에셋이 오면 바꿉니다.
- **QC와 유효시간:** 프레임마다 결측·튐·관통·미끄러짐·관절한계·균형을 검사하고 유효 데이터 시간을 합산합니다(목표 5 h).
- **리타게팅 품질:** 로봇이 사람 동작을 얼마나 잘 옮겨 받았는지 로봇에 상관없는 기준(팔다리 방향, 발 접촉, 관절 한계, 자기 충돌)으로 0–100점을 매기고, 같은 클립으로 로봇끼리 비교합니다.
- **비교:** 여러 소스를 같은 G1에 올려 나란히 보거나, 골반 기준으로 겹쳐 부위별 차이를 색으로 봅니다.
- **물리 검증:** Isaac Sim PhysX로 "로봇이 이 동작을 자기 발로 할 수 있는가"를 재고, 넘어지면 첫 원인을 진단합니다. MuJoCo에서 공개 추적 정책(GMT)으로 균형 제어를 켠 경우와 끈 경우를 비교합니다.
- **AI 연동:** 명령줄 `retlens-cli`(JSON)와 떠 있는 창의 로컬 HTTP API, Claude Code 스킬 형식의 사용 안내.

## 시작하기

**설치판 (권장):** [Releases](https://github.com/rlawlsgus/retarget-lens/releases)에서 `RetLens-<버전>-win64.zip`을 받아 풀고 `RetLens.exe`를 실행합니다. FBX·SMPL-X·물리 기능은 "파일 > 환경 설정"에서 Blender, SMPL-X 모델, Isaac Sim을 지정하면 켜집니다. 사용법은 [docs/retlens.md](docs/retlens.md)에 있습니다.

**저장소에서 (개발):** [docs/setup.md](docs/setup.md)대로 conda 환경 `k-humanoid`를 만든 뒤:

```powershell
conda activate k-humanoid
scripts\editor.bat                                   # RetLens (더블클릭으로도 실행)
python tools\retlens_cli.py info                     # 환경 점검 (JSON)
python -m pytest tests                               # 테스트
```

## 문서

| 문서 | 내용 |
|---|---|
| [docs/retlens.md](docs/retlens.md) | RetLens 사용 안내: 화면, 열 수 있는 파일, 물리 모드, 분석 지표, 겹쳐 비교, 환경 설정, AI 연동 |
| [docs/pipeline.md](docs/pipeline.md) | 명령줄 파이프라인: 리타게팅(평활화·디딤발 평평·스윙 발 보정), QC 기준, 리타게팅 품질(로봇 비교), Isaac 재생·물리·진단, 비교 뷰어, 지원 포맷, 알려진 한계 |
| [docs/results.md](docs/results.md) | 검증 결과 기록(날짜별): 리타겟 품질, 포맷 비교, 물리 결과, QC 임계값 조정 근거 |
| [docs/data.md](docs/data.md) | 데이터 출처·라이선스(공개 가능 여부), `data/`·`reports/` 구성과 다시 만드는 법 |
| [docs/setup.md](docs/setup.md) | 개발 환경: 버전, 드라이버, 설치 순서, 잠금 파일, 네트워크, 직접 받아야 하는 것 |
| [docs/packaging.md](docs/packaging.md) | 설치판 구조, 빌드, 라이선스, 남은 일 |
| [docs/release.md](docs/release.md) | GitHub Releases에 빌드 올리는 순서 |
| [docs/cmu_motion_labels.md](docs/cmu_motion_labels.md) | CMU 시도 번호 → 동작 설명, 이 PC에 있는 형식 |
| [docs/research/](docs/research/) | 사전 조사: 모캡 포맷·공개 데이터셋·리타게팅 툴(`mocap_survey.md`), C3D 검토(`c3d_review.md`), 균형 제어와 학습 데이터 처리(`balance_control_review.md`) |
| [.claude/skills/retlens/SKILL.md](.claude/skills/retlens/SKILL.md) | AI 에이전트용 RetLens 사용 안내 |

## 폴더 구조

```
khumanoid/            코어 패키지 (numpy 위주, Isaac Sim 파이썬에서도 import 가능)
  io/                 포맷별 로더 (BVH, FBX via Blender, C3D, AMASS SMPL/SMPL-X, 로봇 npz·csv·pkl)
  gmr/                GMR(MIT)에서 가져온 IK 풀이와 G1 설정 (torch 없음)
  retarget.py         리타게팅 (T-pose 설정 생성, 평활화, 디딤발 평평 보정, 스윙 발 보정)
  qc.py, analysis.py, stability.py, diagnosis.py   QC, 비교 지표, 균형(CoM·ZMP), 넘어짐 원인
  retarget_quality.py 리타게팅 품질 (로봇에 상관없는 지표와 점수)
  compare.py, markers.py   여러 포맷을 같은 로봇으로 불러오기(캐시), C3D 마커
  physics_runner.py   Isaac 작업(물리·녹화)을 백그라운드 프로세스로 돌리고 캐시
  policy_replay.py    균형 켬/끔 비교: MuJoCo에서 제어기 없는 PD 재생 vs GMT 추적 정책
  paths.py, settings.py    파일 위치(저장소/설치판), 환경 설정과 점검
  app/                RetLens: editor.py(Qt 창), scene.py(화면과 무관한 장면 코어), robots.py(배치 메시),
                      api_core.py / api_server.py(AI용 JSON 코어, 로컬 HTTP API), runtime.py(로그·오류 창)
tools/                명령줄: editor.py, retlens_cli.py, retarget.py, qc_report.py, isaac_replay.py,
                      compare_viewer.py, compare_report.py, physics_report.py, policy_replay.py, retarget_benchmark.py,
                      fetch_samples.py, make_samples.py,
                      cmu_motion_index.py, cmu_frame_rates.py, stage_resources.py, make_icon.py
configs/              qc.yaml (QC 임계값, 목표 시간), physics.yaml (물리 재생·판정 기준)
scripts/              setup_env.ps1, install_isaacsim.ps1, install_gmr.ps1, install_gmt.ps1 (추적 정책, 선택), editor.bat,
                      build_retlens.ps1 (실행파일), package_release.ps1 (릴리즈 zip), refresh_reports.ps1 (데이터·리포트 다시 만들기)
packaging/            PyInstaller 스펙, exe 진입점, 아이콘 (svg 원본, ico)
tests/                pytest
docs/                 문서 (위 표). docs/internal/은 내부 문서 자리 (git 제외)
data/, reports/       원본 모캡, 리타겟, 캐시 / QC·비교·물리 리포트, 동영상 (git 제외, docs/data.md)
models/               SMPL-X 바디모델 (git 제외, 직접 받음)
build/, dist/         빌드 중간 파일 / 결과물 (git 제외)
```

## 데이터와 라이선스

- 코드는 [LICENSE](LICENSE)를 따르고, `khumanoid/gmr/`은 GMR의 MIT 라이선스(파일 동봉)입니다.
- 공개 데이터셋에 쓸 수 있는 공개 샘플은 **CMU**(BVH·FBX·C3D)뿐입니다. AMASS·LAFAN1·Unitree csv와 그 파생물은 내부 검증 전용이고, SMPL-X 모델은 재배포할 수 없습니다([docs/data.md](docs/data.md)).
- 공개 5 h 데이터는 자체 촬영분(공개 동의서 확보)으로 채우는 것이 안전합니다.
