# RetLens 배포 구조

설치판(실행파일)을 어떻게 만들고 무엇이 들어가는지, 남은 일은 무엇인지 정리합니다. 릴리즈를 올리는 순서는 [release.md](release.md)에 있습니다.

## 지금 상태 (2026-10-19)

- **내려받아 바로 쓰는 한 폴더 실행파일이 있습니다.** `scripts\build_retlens.ps1 -Samples`가 `dist\RetLens\`를 만들고(창 프로그램 `RetLens.exe`와 명령줄 `retlens-cli.exe`가 `_internal\`을 함께 씀), `scripts\package_release.ps1`이 릴리즈용 zip과 SHA-256을 만듭니다.
- conda 없는 조건에서 3D, 리타게팅(BVH, 묶인 샘플 BVH로 C3D), 발 지표, 분석 표, 로그 파일, 설치판 배치의 Isaac 물리·녹화까지 확인했습니다(아래 "작업 기록").
- **받는 사람이 따로 설치하는 것**은 기능별로, 필요할 때만입니다. 위치는 RetLens "환경 설정"에서 정합니다.

  | 기능 | 필요한 것 |
  |---|---|
  | BVH, 로봇 모션(npz·csv·pkl), C3D(같은 촬영의 BVH가 있을 때) | 없음 |
  | FBX | Blender 4.5 LTS (GPL, 별도 설치) |
  | AMASS SMPL-X | SMPL-X 모델 파일 (재배포 금지, 사용자가 등록해 받음) |
  | 물리 모드·동영상 | NVIDIA RTX GPU, Isaac Sim 6.1 (사용자가 설치하고 EULA 동의), 인터넷(로봇 에셋) 또는 로컬 로봇 USD |

- 대상 PC: Windows 10/11 64비트, WebGL이 되는 GPU(Direct3D 11), 디스크 약 1.2 GB(물리·녹화는 Isaac Sim 수십 GB 별도).

### 남은 일

1. 설치 파일(Inno Setup)과 제3자 라이선스 고지 묶음(Qt·WebEngine LGPL/BSD, qpsolvers LGPL 등). 지금은 zip을 풀어 쓰고, 고지는 GMR·Unitree G1만 `_internal\licenses`에 있습니다. 깨끗한 Windows(VM)에서 설치·실행 시험도 함께 합니다.
2. 크기 줄이기: 이 conda 환경의 numpy·scipy가 Intel MKL에 링크되어 약 550 MB가 MKL입니다. OpenBLAS로 만든 빌드 전용 환경에서 빌드하면 약 600 MB로 줄어듭니다.
3. (공개 배포 시) 코드 서명. 서명이 없으면 Windows SmartScreen 경고가 뜹니다("추가 정보 > 실행"으로 실행은 됨).
4. 오프라인 G1 USD로 물리 실행 확인. 로봇 USD 옵션은 있지만 실제 로컬 사본으로는 아직 돌려 보지 않았습니다.
5. Isaac 없이도 물리를 볼 수 있게 MuJoCo 물리를 대안으로 둘지 결정.

## 설치판 구성

```
RetLens\                            릴리즈 zip을 푼 폴더 (어디에 두어도 됨)
  RetLens.exe                       창 프로그램 (PyInstaller onedir, 창 모드)
  retlens-cli.exe                   AI·스크립트용 명령줄 (같은 _internal을 씀)
  _internal\                        Python, Qt/WebEngine, numpy/scipy, MuJoCo, viser(client/build만),
                                    khumanoid (GMR에서 가져온 IK 풀이 포함)
    assets\unitree_g1\              G1 URDF·MJCF·메시 (BSD-3)
    assets\gmt_g1\g1.xml            GMT의 23 DoF G1 MuJoCo 모델 (위 메시 사용, 물리 모드 "없음 (MuJoCo)")
    configs\  data\cmu_metadata.csv  docs\ (도움말)  ai\retlens\SKILL.md (AI 가이드)
    isaac\khumanoid\, isaac\tools\isaac_replay.py   Isaac 파이썬이 읽는 일반 소스
    licenses\                       제3자 라이선스 고지
    samples\                        (-Samples) CMU BVH·C3D
%LOCALAPPDATA%\RetLens\             settings.json, cache\(리타겟·FBX·물리), uploads\, logs\, api.json
문서\RetLens\                        videos\ (동영상), motions\ (내 모션 폴더)
레지스트리 (QSettings RetLens)       창 배치, Isaac EULA 동의
따로 설치 (환경 설정에서 지정)         Isaac Sim, Blender 4.5, SMPL-X 모델 폴더
```

## 빌드

```powershell
conda activate k-humanoid
powershell -ExecutionPolicy Bypass -File scripts\build_retlens.ps1 -Samples   # -> dist\RetLens\ (약 4분)
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1          # -> dist\RetLens-<버전>-win64.zip + .sha256
```

- `tools\stage_resources.py`가 `build\resources\`에 리소스를 모으고(라이선스 제한 데이터는 넣지 않음, `tests/test_stage_resources.py`가 확인), `packaging\retlens.spec`이 묶습니다.
- 빼는 것: torch, smplx, 외부 GMR 패키지, Isaac, osqp·proxsuite·scs(QP 풀이기, GMR은 daqp만 씀), cv2, PyOpenGL, cryptography.
- 버전은 `khumanoid/__init__.py`의 `__version__`입니다. "도움말 > 정보"와 `retlens-cli info`에 나옵니다.
- 아이콘: `packaging\retlens_icon.svg`(벡터 원본) → `python tools\make_icon.py` → `packaging\retlens.ico`, `khumanoid\app\icon.png`.
- `build\`는 빌드 중간 파일(약 230 MB)이라 지워도 되고, 다음 빌드가 다시 만듭니다. `dist\`는 결과물입니다. 둘 다 git에 넣지 않습니다.

## 라이선스 (동봉 가능 여부)

| 구성 | 라이선스 | 동봉 |
|---|---|---|
| Python, numpy, scipy | PSF / BSD | 가능 |
| PySide6, Qt | LGPL-3.0 | 가능. DLL을 바꿀 수 있게 두고(onedir) 라이선스를 고지 |
| Qt WebEngine (Chromium) | BSD-3 / LGPL | 가능. 고지 필요 |
| viser | MIT | 가능 |
| GMR | MIT | 가능 (필요한 부분만 가져와도 됨) |
| mujoco, mink | Apache-2.0 | 가능 |
| qpsolvers | LGPL-3.0 | 가능. 파이썬 파일 그대로 두고 고지 |
| daqp, trimesh, yourdfpy, ezc3d | MIT | 가능 |
| torch / MKL | BSD-3 / Intel Simplified | 가능 (빼는 편이 나음) |
| Unitree G1 URDF·메시 | BSD-3 | 가능 |
| GMT G1 MuJoCo 모델 (`g1.xml`) | Apache-2.0 (GMT, Unitree BSD-3 설명 기반) | 가능. `licenses\GMT-LICENSE.txt` 동봉 |
| **GMT 추적 정책 (`pretrained.pt`)** | Apache-2.0, README: "연구용" | **넣지 않음** (PyTorch도 빠짐) |
| **smplx (코드)** | **MPI 비상업** | **넣지 말 것** (아래 "작업 기록" 4번) |
| **SMPL-X 모델 파일** | **MPI 비상업, 재배포 금지** | **불가.** 사용자가 받아 폴더를 지정 |
| **AMASS·LAFAN1 데이터** | 비상업 / CC BY-NC-ND | **불가** |
| CMU 데이터 (BVH, FBX, C3D) | 재배포 가능, 판매만 금지 | 샘플로 넣을 수 있음 |
| **Blender** | GPL (별도 프로세스) | 별도 설치를 권장 |
| **Isaac Sim** | NVIDIA 라이선스 | **불가.** 사용자가 설치하고 EULA에 동의 |

## 작업 기록 (2026-10-19)

처음 점검(2026-10-19 오전) 때는 conda 환경·저장소 구조·`..\GMR`·고정 설치 경로가 있어야만 돌았습니다. 아래 순서로 고쳤습니다.

1. ~~경로 분리 모듈~~ **완료 (2026-10-19), `khumanoid/paths.py`.**
   - **배치는 둘입니다.** `dev`는 저장소 그대로이고, `installed`는 `sys.frozen`이거나 `KHUMANOID_LAYOUT=installed`일 때입니다.
   - **설치판이 쓰는 곳**
     - `%LOCALAPPDATA%\RetLens\`: `cache\retarget`, `cache\fbx`, `cache\physics`, `uploads`, `logs`, `models`(SMPL-X 기본 위치)
     - `문서\RetLens\`: `videos`, `motions`(OneDrive로 옮긴 문서 폴더도 찾음)
   - **설치판 프로그램 폴더(리소스)에 넣을 것.** 6단계 스펙이 이 배치를 만듭니다.
     - `configs\physics.yaml`, `configs\qc.yaml`
     - `assets\unitree_g1\…`(G1 URDF·메시)
     - `data\cmu_metadata.csv`(동작 라벨)
     - `docs\retlens.md`, `docs\cmu_motion_labels.md` (처음에는 README.md)
     - `samples\`(선택)
     - `isaac\khumanoid\…`와 `isaac\tools\isaac_replay.py`(Isaac 파이썬이 읽는 일반 소스)
     - `khumanoid\io\blender_fbx_script.py`, `khumanoid\io\cmu_frame_rates.json`(모듈 옆 데이터 파일)
   - **바꿀 수 있는 위치:** `KHUMANOID_RESOURCE_DIR`, `KHUMANOID_USER_DIR`, `KHUMANOID_DOCS_DIR`, `SMPL_MODEL_DIR`.
   - **Isaac 작업:** 실행 폴더가 `isaac_root()`이고, `--qc-config`·`--physics-config`를 항상 넘겨서 Isaac 쪽 폴더 구조에 기대지 않습니다.
   - 다른 드라이브의 경로를 표시해도 오류가 나지 않습니다(`paths.rel`).
   - "도움말 > 정보"에 모든 위치가, "파일 > 데이터 폴더 열기"에 사용자 데이터 폴더가 있습니다.
   - **확인**
     - 테스트: `tests/test_paths.py`. 설치판 배치에서 쓰는 곳이 모두 사용자 폴더이고, 프로그램 폴더·저장소에는 쓰지 않는지 봅니다.
     - 설치판 배치로 실제 편집기를 띄워 봤습니다(G1 에셋·configs·라벨을 복사한 임시 프로그램 폴더). 리타겟 캐시는 임시 사용자 폴더에만 생겼고, 저장소 캐시 파일 수는 179개 그대로였습니다.
2. ~~환경 설정 화면과 시작 점검~~ **완료 (2026-10-19).**
   - 코어 `khumanoid/settings.py`(Qt 없음, 표준 라이브러리만)
     - 값은 `settings.json`(사용자 데이터 폴더)에 저장하고, 편집기·비교 뷰어·명령줄이 함께 씁니다.
     - 찾는 순서는 설정 → 환경변수 → 기본 위치입니다.
       - Isaac은 설치 폴더나 `python.bat`이고, 버전은 `VERSION`에서 읽습니다.
       - Blender는 `blender.exe`이고, 버전은 폴더 이름에서 읽습니다.
       - SMPL-X는 `smplx\SMPLX_*.npz`가 있는 폴더이고, `smplx` 폴더 자체를 골라도 됩니다.
     - 동영상 폴더와 모션 폴더(기본 + 추가)도 여기서 정합니다.
     - `check_all()`은 로봇 모델(필수), GMR, Isaac, Blender, SMPL-X, 동영상 폴더, 모션 폴더를 점검합니다. 결과에는 "쓸 수 없는 기능"과 고치는 방법이 들어 있습니다.
   - 물리 실행기(`isaac_command`)와 FBX(`find_blender`)는 실행할 때마다 설정을 다시 읽습니다. SMPL-X·동영상 폴더는 저장하면 바로 장면에 반영됩니다(`MotionScene.apply_settings`).
   - 편집기
     - "파일 > 환경 설정"(Ctrl+,): 경로 칸·찾아보기·받는 곳 링크가 있고, 입력하는 동안 점검합니다. 자동으로 찾은 경로는 칸에 흐리게 보입니다. 모션 폴더 목록과 프로그램 상태(로봇 모델, GMR, 사용자 데이터 폴더 열기)도 있습니다.
     - 상태바 "환경 ✓ / ⚠ N"을 누르면 환경 설정이 열립니다.
     - 처음 실행할 때 빠진 것이 있으면 자동으로 엽니다(`--quit-after` 스모크 테스트에서는 열지 않음).
     - 물리 모드·동영상 저장 전에 Isaac을 점검합니다. 모션 열기가 Blender·SMPL-X·GMR 문제로 실패하면 "환경 설정 열기" 버튼이 나옵니다.
     - 로봇 모델이 없으면 이유를 창으로 보여 주고 끝납니다.
   - 확인: `tests/test_settings.py`. 이 PC(모두 ✓)와 설치판 배치에서 잘못된 Blender 경로·SMPL-X 없음(⚠ 2) 상태로 창을 띄워 봤습니다.
3. ~~G1 에셋 동봉 준비, GMR에서 torch 제거, 동일성 검증~~ **완료 (2026-10-19).**
   - **`khumanoid/gmr/`:** GMR @ `bb1bbe4`(MIT)에서 필요한 것만 가져왔습니다.
     - IK 풀이 `motion_retarget.py`와 G1 IK 설정 JSON은 바이트 단위로 같습니다.
     - `params.py`는 G1만 남기고 에셋 위치를 `paths.robot_assets_dir()`에서 받습니다.
     - LICENSE를 함께 넣었습니다.
     - GMR 패키지의 `__init__`(torch, MuJoCo 뷰어, imageio)는 더 이상 불러오지 않습니다.
   - **LAFAN1/Nokov BVH:** GMR에 딸린 Ubisoft LAFAN1 리더(라이선스 불명확) 대신 `khumanoid.io.bvh`로 읽습니다(`retarget.gmr_bvh_frames`).
   - **동일성 (외부 GMR 결과와 비교)**
     - T-pose BVH(02_03), FBX(02_01), SMPL-X(02_01), `smplx-gmr`는 비트 단위로 같습니다.
     - LAFAN1(300프레임)은 사람 프레임 차이가 2×10⁻¹⁵ m, 관절각 차이가 2.8×10⁻¹² rad 이하입니다(부동소수점 반올림).
     - 설치판 배치에서 torch·smplx·외부 GMR을 import할 수 없게 막고 리타겟해도 같은 결과가 나오고, 셋 다 불러오지 않습니다.
   - **에셋 동봉 준비:** `tools/stage_resources.py <폴더> [--samples]`가 설치판 리소스 폴더를 만들고 빠진 것이 없는지 점검합니다. G1 메시는 git에 넣지 않고 이 단계에서 복사합니다. 들어가는 것은 다음과 같습니다(약 56 MB, 샘플 포함 64.5 MB).
     - configs
     - assets/unitree_g1(URDF, MJCF, 메시, BSD-3 LICENSE)
     - CMU 라벨
     - README·docs
     - isaac/(khumanoid + isaac_replay.py 일반 소스, 5단계의 파일 준비)
     - licenses/
   - 확인: `tests/test_retarget.py`(torch 없이 import, GMR 원래 LAFAN1 리더와 비교), `tests/test_stage_resources.py`(빠진 것 없음, 라이선스 제한 데이터 없음).
4. **사실상 해결됨.** 기본 SMPL-X 경로(`smplx`)는 처음부터 자체 numpy FK(`khumanoid/io/smpl.py`)였습니다. `smplx` 패키지와 torch는 개발용 비교 경로 `--format smplx-gmr`에만 쓰입니다(없으면 그 경로만 안내 메시지로 실패). 남은 일은 6단계 스펙에서 torch·smplx·외부 GMR을 빼는 것뿐입니다.
5. ~~Isaac용 소스 동봉, 설치판에서 Isaac 실행 확인, 로컬 로봇 USD 옵션~~ **완료 (2026-10-19).**
   - **설치판 배치에서 실제 실행**
     - 조건: `stage_resources.py`로 만든 리소스 폴더, 임시 사용자·문서 폴더, Isaac은 독립 설치본 `C:\isaacsim\python.bat`(배포 사용자와 같은 경로).
     - 물리: 02_03이 78초 만에 끝났고 결과는 사용자 캐시에 생겼습니다. 저장소 개발 환경에서 같은 키로 낸 결과와 관절각·루트 궤적·판정이 **비트 단위로 같습니다**.
     - 녹화: 37초 만에 `문서\RetLens\videos`에 MP4(304 KB)가 생겼습니다.
     - Isaac 파이썬은 리소스 폴더의 `isaac\`(일반 소스)에서 `isaac_replay.py`를 돌렸습니다. `--qc-config`·`--physics-config`도 리소스 폴더를 가리켰습니다.
   - **로봇 USD 옵션**
     - 환경 설정 "로봇 USD (선택)" / `settings.robot_usd`에 로컬 USD 파일이나 URL(사내 Nucleus 등)을 넣습니다. 비우면 지금처럼 NVIDIA 에셋 서버의 G1을 씁니다(인터넷 필요, `Robots_Multiphysics/Unitree/G1/g1.usda`).
     - 지정하면 물리·녹화 작업에 `--robot-usd`로 넘기고, 결과 캐시 키에도 넣어 다른 에셋의 결과와 섞이지 않습니다. 기본값이면 키가 그대로라 기존 결과를 그대로 씁니다.
     - 확인: 같은 에셋 주소를 명시해 돌렸더니 새 키로 따로 계산됐고, 결과는 기본 실행과 비트 단위로 같았습니다(`tests/test_settings.py`도 인자·키를 확인).
     - 실제 로컬 파일(오프라인 G1 사본)로는 아직 돌려 보지 않았습니다. 오프라인 사본을 만들려면 NVIDIA 에셋을 내려받아야 합니다. Isaac Sim 오프라인 에셋 팩을 쓰거나, g1.usda와 그것이 참조하는 파일을 함께 복사해야 합니다.
6. ~~PyInstaller 스펙·빌드 스크립트, 로그 파일, 오류 대화상자, 검은 창 제거~~ **완료 (2026-10-19).**
   - **빌드:** `powershell -ExecutionPolicy Bypass -File scripts\build_retlens.ps1 [-Samples]` → `dist\RetLens\RetLens.exe`(창 모드, 한 폴더).
     - `tools\stage_resources.py`로 `build\resources`를 만들고, `packaging\retlens.spec`(PyInstaller 6.22, conda-forge, 사용자 승인 후 설치)으로 묶습니다. 빌드는 약 4분 걸립니다.
     - torch·smplx·외부 GMR·Isaac은 빼고, 다른 QP 풀이기(osqp·proxsuite·scs)도 뺍니다. osqp는 네이티브 백엔드가 빠지면 import가 RuntimeError로 실패해 mink까지 막기 때문입니다(GMR은 daqp만 씀). cv2·PyOpenGL·cryptography도 선택 의존성이라 뺍니다.
     - viser 웹 클라이언트는 `client/build`만 넣습니다.
   - **아이콘:** `packaging\retlens_icon.svg`(벡터 원본: 렌즈 + 사람)에서 `python tools\make_icon.py`로 `packaging\retlens.ico`(16–256 px 9종, exe 아이콘)와 `khumanoid\app\icon.png`(창·작업 표시줄 아이콘)를 만듭니다. 저장소에서 실행해도 작업 표시줄에 RetLens 아이콘이 나옵니다(AppUserModelID).
   - **로그·오류(`khumanoid/app/runtime.py`)**
     - 설치판이거나 콘솔이 없으면 출력과 traceback이 `%LOCALAPPDATA%\RetLens\logs\retlens-<시각>.log`에 남습니다(최근 20개 유지, faulthandler 포함).
     - 처리되지 않은 오류는 GUI 스레드든 다른 스레드든 로그에 남기고 "로그 폴더 열기" 버튼이 있는 대화상자로 보여 줍니다(같은 오류는 한 번).
     - 시작 전에 실패하면 Windows 메시지 상자를 띄웁니다. 모션 열기 실패도 로그에 traceback으로 남습니다.
   - **검은 창 제거:** Blender(FBX), `taskkill`, Isaac 안의 ffmpeg 실행에 `CREATE_NO_WINDOW`를 붙였습니다.
   - **WebEngine 샌드박스:** 빌드에서는 `QtWebEngineProcess.exe` 사본을 Qt DLL 옆(번들 최상위)에 두고 `QTWEBENGINEPROCESS_PATH`로 가리킵니다. 그래서 **샌드박스를 켠 채로** 3D가 뜹니다. 저장소(conda)에서는 지금처럼 끕니다.
   - **확인 (깨끗한 조건):** PATH에서 conda를 빼고 사용자·문서 폴더를 임시로 돌려 `RetLens.exe 02_03.bvh 02_01.c3d`를 실행했습니다.
     - 창, 3D, 리타게팅(BVH, 묶인 샘플 BVH로 C3D), 발 지표, 분석 표가 모두 정상이었고, 로그 파일도 생겼습니다.
     - 처음 빌드에서는 osqp 문제로 리타게팅이 실패했고, 위와 같이 고쳤습니다.
   - **AI 연동(추가):** 같은 폴더에 콘솔 프로그램 `retlens-cli.exe`가 함께 빌드됩니다(같은 `_internal` 공유). AI 가이드는 `_internal\ai\retlens\SKILL.md`입니다([retlens.md](retlens.md) "AI 연동").
   - **크기:** `dist\RetLens` 1,163 MB. 그중 약 550 MB가 Intel MKL입니다(이 conda 환경의 numpy·scipy가 MKL BLAS에 링크됨). OpenBLAS로 만든 빌드 전용 환경에서 빌드하면 약 600 MB로 줄어듭니다(다음 할 일).
