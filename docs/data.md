# 데이터와 라이선스

`data/`와 `reports/`는 git에 넣지 않습니다(라이선스 제한 데이터와 생성물). 원본은 `data/raw/`, 나머지는 모두 원본에서 다시 만들 수 있습니다.

## 공개 샘플과 라이선스

`python tools\fetch_samples.py`로 받습니다. 리비전을 고정하고 파일별 해시를 확인하며, 폴더마다 `SOURCE.md`에 출처·리비전·라이선스·해시를 남깁니다.

| 폴더 | 내용 | 라이선스 | 사용 범위 |
|---|---|---|---|
| `data/raw/cmu_bvh` | CMU mocap(cgspeed 2010 BVH 변환본) 6클립, 총 40 s: 02_01 걷기, 02_03 조깅, 16_17 걷다 좌회전(이상 120 Hz), 143_11 상자 들기, 143_13 빨래바구니 들기, 143_28 빗자루질(이상 60 Hz) | CMU 약관(상업 사용·재배포 허용, 데이터 판매 금지) | **공개 데이터셋 사용 가능**. 사사 문구는 SOURCE.md |
| `data/raw/cmu_c3d` | CMU 원본 C3D(Vicon 광학 마커, 41마커 세트) 9개, 7 MB: 위 6클립과 05_02, 143_34, 90_28. mocap.cs.cmu.edu에서 직접 받음(URL·해시는 SOURCE.md) | CMU 약관 | **공개 데이터셋 사용 가능** |
| `data/raw/cmu_fbx` | 위 6클립의 FBX(Hugging Face `gbionics/cmu-fbx`, 0.8 MB, sha256 확인) | CMU 약관 | **공개 데이터셋 사용 가능** |
| `data/raw/cmu_fbx_from_bvh` | 위 6클립 BVH를 Blender로 변환한 FBX(우리가 만든 파생물, 테스트용) | CMU 약관 | 공개 가능 |
| `data/raw/amass_cmu_smplx` | AMASS CMU SMPL-X N 전체(2,080 파일, 8.6 GB, 사용자가 직접 받음). 비교에는 위 BVH와 같은 5클립을 씀(16_17은 AMASS에 없음) | AMASS 비상업 연구 라이선스 | **내부 검증 전용** |
| `data/raw/unitree_lafan1_g1` | Unitree의 LAFAN1→G1 리타겟 csv 4클립(30 fps, 13.3분) | CC BY-NC-ND 4.0 | **내부 검증 전용**. 재배포·파생물 공유 금지 |
| `data/raw/lafan1_bvh` | 같은 4클립의 LAFAN1 원본 BVH(137 MB zip에서 4개만 남김) | CC BY-NC-ND 4.0 | **내부 검증 전용** |

- 리타게팅 결과와 리포트는 원본 라이선스를 따릅니다. `amass_cmu_smplx`, `lafan1_bvh`, `unitree_lafan1_g1`에서 나온 것(`data/retargeted/amass_cmu_smplx/`, `data/retargeted/lafan1_bvh/`, `reports/qc/internal.*`, `reports/compare/lafan1_*`, `reports/retarget_quality/internal/`, `reports/physics/amass_cmu_smplx/`, `reports/videos/internal_lafan1/` 등)은 내부용입니다.
- SMPL-X 바디모델(`models/smplx/`)도 재배포할 수 없어 사용자가 직접 받습니다([setup.md](setup.md) 7절).
- 공개 5 h 데이터는 라이선스 제약 때문에 자체 촬영분(공개 동의서 확보)으로 채우는 것이 안전합니다([조사 자료 2.4절](research/mocap_survey.md)). 공개 샘플 중에서는 CMU만 공개 가능합니다.

## 폴더 구성

| 위치 | 내용 | 만드는 방법 |
|---|---|---|
| `data/raw/<출처>/` | 원본 모캡(위 표) | `tools/fetch_samples.py`, 직접 받기 |
| `data/samples/` | 합성 샘플(사람 BVH 정상/글리치, G1 npz/csv). 테스트가 씀 | `tools/make_samples.py` |
| `data/retargeted/<원본 폴더>/` | 원본 폴더별 G1 리타겟(`<clip>_g1.npz` + `.json`). 권장 설정 `--smooth 6 --swing-clearance 2` | `scripts\refresh_reports.ps1 -Stage retarget` |
| `data/cache/` | 리타겟·FBX·물리 결과 캐시(RetLens·비교 뷰어). 키에 내용·설정·버전이 들어가 지워도 다시 만듦 | 자동 |
| `data/uploads/` | 비교 뷰어 "파일 열기"로 올린 파일 | 자동 |
| `data/settings.json` | 저장소에서 실행할 때의 환경 설정(설치판은 `%LOCALAPPDATA%\RetLens\`) | RetLens 환경 설정 |
| `reports/qc/` | QC·유효시간: `samples`(합성), `cmu_public`(공개 가능한 CMU만, 공개 KPI 집계), `internal`(전부), `cmu_c3d_markers.json`(C3D 마커 QC) | `-Stage reports` |
| `reports/retarget_quality/` | 리타게팅 품질(로봇별 점수표): `summary.md`·`results.json`(공개 가능한 CMU BVH·FBX), `internal/`(AMASS·LAFAN1 포함) | `-Stage reports` |
| `reports/compare/` | 포맷 비교: `cmu_bvh_fbx_smplx.md`(같은 촬영의 BVH/FBX/SMPL-X), `lafan1_gmr_vs_unitree.md`(우리 GMR vs Unitree 공식 리타겟) | `-Stage reports` |
| `reports/sim_check/` | Isaac 헤드리스 검사 JSON·스냅샷(CMU 6클립, 사람+로봇) | `-Stage isaac` |
| `reports/physics/<원본 폴더>/`, `summary.md` | Isaac 물리 재생(하네스 x1) 결과 `<clip>_sim.npz/.json`과 요약 표(CMU 3클립 × 3소스) | `-Stage isaac` |
| `reports/policy/{swing0,swing2,lafan1}/` | 균형 켬/끔 비교(MuJoCo): 제어기 없음 / GMT 추적 정책 결과 `<clip>_<pd\|gmt>_sim.npz/.json`, 두 조건을 나란히 놓은 MP4, `summary.md`(합친 표는 `reports/policy/summary.md`) | `-Stage policy` |
| `reports/videos/` | `kinematic/`(기구학 재생), `physics/`(물리 재생), `internal_lafan1/`, `viewer/`(RetLens·뷰어에서 저장한 영상), `history/`(지난 비교 영상) | `-Stage isaac`, 프로그램 |

```powershell
conda activate k-humanoid
powershell -ExecutionPolicy Bypass -File scripts\refresh_reports.ps1 -Stage retarget,reports        # Isaac 없이, 몇 분
powershell -ExecutionPolicy Bypass -File scripts\refresh_reports.ps1 -Stage isaac -IsaacAcceptEula  # Isaac, 약 30분 (EULA에 동의한 사용자만)
```

- 유효시간(공개 KPI)은 한 촬영을 한 번만 세야 하므로, 사람 모션은 포맷 하나(CMU BVH)만 넣어 집계합니다(`reports/qc/cmu_public`).
- 2026-10-19에 지금 구성으로 모두 다시 만들었습니다. 결과 요약은 [results.md](results.md) 맨 위에 있습니다.
