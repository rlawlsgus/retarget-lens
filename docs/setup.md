# 개발 환경 설치

저장소에서 RetLens와 명령줄 도구를 돌리기 위한 환경입니다. 설치판(`RetLens.exe`)만 쓰는 사람은 이 문서가 필요 없고, [RetLens 사용 안내](retlens.md)의 "환경 설정"만 보면 됩니다.
버전은 개발 PC에서 직접 확인한 값입니다(2026-10-15 설치, 2026-10-19 갱신).

## 1. 한눈에 보기

| 항목 | 요구 사항 | 개발 PC (검증한 구성) |
|---|---|---|
| OS | Windows 11 x64 (스크립트가 PowerShell·Windows 경로 기준) | Windows 11 Enterprise 24H2 (10.0.26100) |
| GPU | NVIDIA RTX. Isaac Sim 6.1 공식 최소는 RTX 4080 / 16 GB | RTX 3070 8 GB. 로봇 1대와 스틱 피겨 재생에는 문제없음 |
| NVIDIA 드라이버 | **595.97 이상** (Isaac Sim 6.x 테스트 드라이버) | 617.42 (CUDA 13.4) |
| CPU / RAM | 특별한 요구 없음 (GMR IK는 CPU, 초당 170–230 프레임) | Intel i5-14500, 64 GB |
| 디스크 | 약 32 GB (아래 표) | – |
| Isaac Sim | **6.1.0** standalone zip, `C:\isaacsim`에 전역 설치 | `VERSION`: 6.1.0-rc.26+release.49347.2d230af4.gl |
| conda | Miniconda 또는 Miniforge, **conda-forge 채널만** | conda 26.7.1 (Miniconda, `%LOCALAPPDATA%\miniconda3`) |
| Python | 3.12 (Isaac Sim 6.1 내장 Python과 같은 마이너 버전) | env 3.12.15 / Isaac 내장 3.12.13 |
| GMR | YanjieZe/GMR 커밋 `bb1bbe40774794fceb2a7c579a3464a28e68c844` (MIT), 프로젝트 폴더 밖 `..\GMR` | 같음 |
| Blender | FBX 입력에만 필요. **4.5 LTS** 포터블 zip, `C:\blender`(또는 `BLENDER` 환경변수) | 4.5.14 LTS (`C:\blender\blender-4.5.14-windows-x64`) |
| ffmpeg | 선택. `isaac_replay.py --video`의 MP4 출력용(없으면 GIF), PATH에 있어야 함 | 2024-09-22 gyan.dev full build, `C:\ffmpeg\bin` |
| 웹 브라우저 | 비교 뷰어용 (WebGL). 기본 주소 `http://127.0.0.1:8080`, 이 PC에서만 접속 | Chromium 계열에서 확인 |
| 인터넷 | 설치와 Isaac 로봇 에셋(G1 USD) 로딩에 필요 (6절) | – |

디스크 사용량:

| 항목 | 크기 |
|---|---|
| Isaac Sim zip (설치 후 지워도 됨) | 10.4 GB |
| Isaac Sim 설치 폴더 `C:\isaacsim` | 18.3 GB (셰이더 캐시는 사용자 폴더에 따로 쌓임) |
| conda env `k-humanoid` | 2.2 GB |
| GMR 부분 체크아웃 `..\GMR` | 53 MB |
| Blender 4.5.14 `C:\blender` (FBX용, zip 380 MB는 지워도 됨) | 약 1.2 GB |
| 공개 샘플·리타겟 결과 `data/` | 30 MB (받는 중에는 LAFAN1 zip 137 MB가 잠깐 필요) |

## 2. 설치 순서

```powershell
# 0) 드라이버 확인: 595.97 이상
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv

# 1) Isaac Sim 6.1.0 -> C:\isaacsim (zip 10.4 GB, MD5 확인)
powershell -ExecutionPolicy Bypass -File scripts\install_isaacsim.ps1

# 2) conda env + Isaac Sim 연결 훅 + GMR (environment.yml, install_gmr.ps1)
powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1
conda activate k-humanoid

# 3) 공개 샘플 (선택)
python tools\fetch_samples.py

# 4) Blender 4.5 LTS (선택, FBX 입력용): zip을 C:\blender에 풀기만 하면 됨
#    https://download.blender.org/release/Blender4.5/blender-4.5.14-windows-x64.zip
#    380 MB, sha256 b9533d2397ac1984db4466fb23a7a4649391cca93f6e84209f9bcc60d071c8b9
Expand-Archive blender-4.5.14-windows-x64.zip -DestinationPath C:\blender
```

- Isaac Sim zip은 `https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.1.0-windows-x86_64.zip`이고 MD5는 `a07968e980072c9ca27b2166443e2d89`입니다.

### Isaac Sim 6.1.0: 전역 설치 (`C:\isaacsim`)

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

### conda 환경 `k-humanoid`

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1
conda activate k-humanoid
```

- [environment.yml](../environment.yml)로 환경을 만듭니다. Python 3.12, numpy 2.3, scipy 1.17로 Isaac Sim 6.1 내장 버전과 맞춰 고정되어 있습니다.
- activate 훅이 `C:\isaacsim`을 연결합니다. 그래서 env 안의 `python`에서 바로 `from isaacsim import SimulationApp`이 됩니다. Isaac Sim 파일은 env에 복사되지 않습니다.
- 이 네트워크는 Anaconda `defaults` 채널이 막혀 있어(HTTP 429, 클라이언트 등록 필요) conda-forge만 씁니다.
- 마지막에 아래 GMR 설치까지 실행합니다(`-SkipGmr`로 생략).
- 모션 편집기용 PySide6와 qt6-webengine(약 180 MB, 둘 다 Qt 6.11)도 들어 있습니다. 기존 환경에 더할 때는 `conda install --override-channels -c conda-forge qt6-webengine=6.11.2`입니다.

### GMR 리타게터 (`..\GMR`, 프로젝트 폴더 밖)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_gmr.ps1
```

- [GMR](https://github.com/YanjieZe/GMR)(MIT)은 패키지 인덱스에 없어서, 고정 커밋(`bb1bbe4`)에서 코드와 `assets/unitree_g1`만 받습니다(약 53 MB, 전체 트리는 1.2 GB). 파일마다 git blob SHA-1을 확인합니다.
- 받은 폴더(`C:\Users\<user>\Documents\Github\GMR`)를 env의 `gmr_k_humanoid.pth`로 연결합니다(`pip install -e`와 같은 효과, git·빌드 도구 불필요).
- GMR 의존성은 environment.yml에 있습니다. conda-forge: mujoco-python 3.11.0(Isaac Sim 내장 버전과 동일), qpsolvers+daqp 등. PyPI: mink 1.3.0(conda-forge에 없음). pytorch CPU와 smplx 0.1.28(PyPI)은 개발용 비교에만 씁니다(아래).
- **리타게팅이 쓰는 GMR 코드는 저장소에 들어 있습니다**(`khumanoid/gmr/`, 2026-10-19).
  - GMR 패키지는 import할 때 torch(자기 운동학 모델), MuJoCo 뷰어, imageio까지 불러오지만, 리타게팅에는 필요 없습니다.
  - 그래서 IK 풀이(`motion_retarget.py`)와 G1 IK 설정 JSON은 그대로 가져오고, 설정 표(`params.py`)는 G1만 남겨 가져왔습니다(MIT, LICENSE 동봉). 필요한 것은 mink·MuJoCo·scipy·rich뿐입니다.
  - LAFAN1/Nokov BVH는 GMR에 딸린 LAFAN1 리더(Ubisoft 저장소 코드) 대신 `khumanoid.io.bvh`로 같은 좌표 규약에 맞춰 읽습니다(`gmr_bvh_frames`).
  - 결과는 이전과 같습니다. T-pose BVH·FBX·SMPL-X·`smplx-gmr`는 비트 단위로 같고, LAFAN1은 관절각 차이가 2.8×10⁻¹² rad 이하입니다(`tests/test_retarget.py`가 GMR 원래 리더와 비교).
  - `..\GMR` 체크아웃은 이제 G1 메시(`assets/`)와 개발용 비교에만 씁니다.
- torch와 `smplx`는 개발용 `--format smplx-gmr` 비교 경로에만 씁니다. 기본 SMPL-X 경로는 자체 numpy FK(`khumanoid/io/smpl.py`)입니다. `smplx` 코드는 MPI 비상업 연구 라이선스라 배포판에 넣지 않습니다.
- env에 torch가 생기면 `from isaacsim import SimulationApp`이 Kit 시작 전에 env의 torch와 numpy를 불러와 Isaac 확장이 깨집니다(numpy.fft DLL 오류). `tools/isaac_replay.py`는 그 import 동안만 torch를 숨겨 해결했습니다. 다른 Isaac 스크립트를 이 env에서 돌릴 때도 같은 처리가 필요합니다.

### Blender 4.5 LTS: FBX 읽기용 (`C:\blender`, 프로젝트 폴더 밖)

FBX는 Autodesk 비공개 포맷이라 Blender의 FBX 임포터로 읽습니다. 설치 프로그램 없이 공식 zip을 풀기만 합니다.

```powershell
# download.blender.org/release/Blender4.5/blender-4.5.14-windows-x64.zip (380 MB, sha256 b9533d23…c8b9)
Expand-Archive blender-4.5.14-windows-x64.zip -DestinationPath C:\blender
```

- RetLens "환경 설정" → `$BLENDER` → `C:\blender\*\blender.exe` → PATH 순서로 찾습니다(`khumanoid/settings.py`). 다른 곳에 풀었으면 환경 설정에서 blender.exe를 고르거나 `BLENDER=<blender.exe 경로>`를 설정하세요.
- 클립마다 Blender를 헤드리스로 띄워(약 2초) 관절 궤적을 뽑고 `data/cache/fbx/`에 캐시합니다. BVH·SMPL-X만 쓰면 Blender는 필요 없습니다.
- 처음에는 PyPI `ufbx` 0.0.5(파이썬 바인딩)를 시험했지만, 노드 부모를 읽을 때 접근 위반으로 죽거나 틀린 값을 돌려줘 쓰지 않습니다(바인딩 이슈 #12와 같은 증상).
## 3. Python 환경 `k-humanoid`

정의는 [environment.yml](../environment.yml)이고, 개발 PC에 실제로 설치된 버전은 아래와 같습니다. 같은 패키지 빌드까지 맞추려면 4절의 잠금 파일을 쓰세요.

| 패키지 | 버전 | 출처 | 용도 / 고정 이유 |
|---|---|---|---|
| python | 3.12.15 | conda-forge | Isaac Sim 6.1 내장 3.12와 맞춤 |
| numpy | 2.3.5 | conda-forge | `=2.3` 고정. Isaac 내장 2.3.1과 같은 마이너 |
| scipy | 1.17.1 | conda-forge | `=1.17` 고정. Isaac 내장 1.17.0과 같은 마이너 |
| pandas | 3.0.6 | conda-forge | QC 리포트 |
| matplotlib | 3.11.2 | conda-forge | |
| pyyaml | 6.0.3 | conda-forge | `configs/qc.yaml` |
| tqdm | 4.70.1 | conda-forge | |
| ezc3d | 1.7.2 | conda-forge | C3D(광학 마커) 로더 |
| pytest | 9.1.1 | conda-forge | |
| mujoco-python | 3.11.0 | conda-forge | `=3.11.0` 고정. GMR IK. Isaac 내장(isaacsim.pip.newton) 3.11.0과 같음 |
| qpsolvers / daqp | 4.13.0 / 0.10.3 | conda-forge | GMR(mink)의 QP 솔버 |
| loop-rate-limiters | 1.2.0 | conda-forge | GMR 의존성 |
| rich / natsort / imageio | 14.3.4 / 8.4.0 / 2.38.1 | conda-forge | GMR 의존성. rich는 viser 때문에 15 미만 |
| viser | 1.1.1 | conda-forge | 비교 뷰어(`tools/compare_viewer.py`)의 브라우저 3D 화면과 GUI (MIT) |
| yourdfpy / trimesh / plotly | 0.0.60 / 4.12.2 / 7.1.0 | conda-forge | 뷰어의 G1 URDF 로딩, 그래프 |
| pytorch (CPU) | 2.10.0 (cpu_mkl) | conda-forge | 개발용만: `--format smplx-gmr` 비교, GMR 원본과의 동일성 테스트. 리타게팅과 설치판에는 필요 없음. 이 빌드 때문에 BLAS가 MKL(mkl 2026.1.0)로 바뀜 |
| mink | 1.3.0 | PyPI | GMR의 differential IK (Apache-2.0). conda-forge에 없음 |
| smplx | 0.1.28 | PyPI | 개발용 `--format smplx-gmr` 비교 전용. 코드가 MPI 비상업 연구 라이선스라 설치판에 넣지 않음 |
| pyside6 / qt6-webengine | 6.11.2 / 6.11.2 | conda-forge | RetLens 화면(Qt), 씬 뷰(내장 Chromium) |
| pyinstaller | 6.22.3 | conda-forge | 실행파일 빌드(`scripts\build_retlens.ps1`) |

환경에 들어가는 연결 설정:
- **Isaac Sim 연결 훅** (`setup_env.ps1`이 `etc\conda\activate.d\isaacsim_link.{bat,ps1}`로 설치): `ISAACSIM_PATH`, `CARB_APP_PATH`, `ISAAC_PATH`, `EXP_PATH`를 설정하고 `PYTHONPATH`에 `C:\isaacsim\site`를 붙입니다. 그래서 env의 `python`에서 `from isaacsim import SimulationApp`이 됩니다.
- **GMR 연결** (`install_gmr.ps1`): `Lib\site-packages\gmr_k_humanoid.pth`에 `..\GMR` 경로를 적습니다(`pip install -e`와 같은 효과).
- conda 실행 시 `CONDA_CHANNELS=conda-forge` (아래 6절).

호환성 주의:
- `SimulationApp` 안에서는 Kit의 import 훅이 Isaac에 내장된 numpy·scipy·torch(`omni.isaac.ml_archive`, torch 2.11.0+cu128)를 씁니다. env의 같은 패키지가 Kit 시작 전에 import되면 두 버전이 섞여 확장 로딩이 깨집니다.
- env에 torch가 있으면 `from isaacsim import SimulationApp`이 Kit 시작 전에 env의 torch와 numpy를 불러옵니다. `tools/isaac_replay.py`는 그 import 동안만 torch를 숨겨서 해결합니다. **이 env에서 다른 Isaac 스크립트를 새로 만들 때도 같은 처리가 필요합니다**(isaac_replay.py 상단 참고).
- numpy·scipy·mujoco는 Isaac 내장 버전과 마이너 버전까지 맞춰 두었습니다. 올릴 때는 Isaac Sim 버전과 같이 확인하세요.

## 4. 정확한 재현용 잠금 파일

[environment.lock.txt](../environment.lock.txt)는 개발 PC의 conda 패키지 목록을 빌드와 다운로드 URL까지 그대로 담은 파일입니다(`conda list --explicit`, win-64 전용). 같은 빌드로 env를 만들려면 아래처럼 합니다.

```powershell
$env:CONDA_CHANNELS = "conda-forge"
conda create -n k-humanoid --file environment.lock.txt
conda run -n k-humanoid python -m pip install --no-deps mink==1.3.0 smplx==0.1.28
powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1 -HooksOnly   # 연결 훅 + GMR만 (패키지는 그대로)
```

pip 패키지(mink, smplx)는 잠금 파일에 들어가지 않아 따로 설치합니다.

## 5. Isaac Sim 실행 관련

| 항목 | 내용 |
|---|---|
| 실행 방법 | env 안의 `python tools\isaac_replay.py ...`, 또는 env 없이 `C:\isaacsim\python.bat tools\isaac_replay.py ...` (QC 스크립트는 pandas가 필요해 env에서 실행) |
| EULA | 무인 실행 시 `OMNI_KIT_ACCEPT_EULA=YES` |
| 로봇 에셋 | Unitree G1을 Isaac 에셋 서버에서 실행할 때마다 읽음: `https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.1/Isaac/Robots_Multiphysics/Unitree/G1/g1.usda`. 오프라인이면 `--robot-usd`로 로컬 USD 지정 |
| 렌더링 | 헤드리스 스냅샷·동영상은 RTX 카메라 센서 사용(960×540) |
| 동영상 | `--video`가 PNG 프레임을 만든 뒤 ffmpeg(libx264)로 MP4로 묶음. ffmpeg가 없으면 GIF |
| 물리 재생 | `--physics`: PhysX CPU, 240 Hz(모션 30 fps당 8스텝). 앱 업데이트가 물리를 진행하지 않게(`/app/player/playSimulations` 끔) 하고 `SimulationManager.step`으로만 진행. 설정은 `configs/physics.yaml`. 11초 클립 약 1분(동영상 포함 약 2분) |

## 6. 네트워크와 외부 소스

| 호스트 | 용도 | 필요한 때 |
|---|---|---|
| `downloads.isaacsim.nvidia.com` | Isaac Sim zip | 설치 |
| `conda.anaconda.org/conda-forge` | conda 패키지 | env 생성 |
| `pypi.org`, `files.pythonhosted.org` | mink, smplx | env 생성 |
| `api.github.com`, `raw.githubusercontent.com` | GMR 소스(고정 커밋), CMU BVH | `install_gmr.ps1`, `fetch_samples.py` |
| `media.githubusercontent.com` | LAFAN1 zip (Git LFS) | `fetch_samples.py lafan1` |
| `huggingface.co` | Unitree LAFAN1 G1 csv, CMU FBX(`gbionics/cmu-fbx`) | `fetch_samples.py unitree`, `fetch_samples.py cmu_fbx` |
| `download.blender.org` | Blender 4.5 LTS zip | FBX를 쓸 때 설치 |
| `omniverse-content-production.s3-us-west-2.amazonaws.com` | Isaac 로봇 에셋(G1) | Isaac 재생할 때마다 |

- **`repo.anaconda.com`(Anaconda defaults 채널)은 이 네트워크에서 막혀 있습니다**(HTTP 429, 클라이언트 등록 필요). `setup_env.ps1`은 프로세스에 `CONDA_CHANNELS=conda-forge`를 설정하고, environment.yml도 `nodefaults`입니다. `.condarc`는 건드리지 않습니다.
- `install_gmr.ps1`과 `fetch_samples.py`는 파일마다 해시(git blob SHA-1 또는 LFS SHA-256)를 확인합니다.

## 7. 직접 받아야 하는 것 (라이선스 제한)

| 항목 | 필요한 기능 | 받는 곳 / 둘 곳 |
|---|---|---|
| SMPL-X 바디모델 (`SMPLX_NEUTRAL.npz` 등) | AMASS SMPL-X 로딩·리타게팅 | smpl-x.is.tue.mpg.de 등록 후 다운로드 → `models/smplx/`, `--smpl-model-dir models` 또는 `SMPL_MODEL_DIR` |
| SMPL+H 바디모델 | AMASS SMPL+H 로딩 | mano.is.tue.mpg.de → `models/smplh/` |
| AMASS CMU (SMPL-X N) | BVH vs SMPL-X 비교, CMU 촬영 fps 표 재생성 | amass.is.tue.mpg.de 등록 후 다운로드 → `data/raw/amass_cmu_smplx/CMU/` (8.6 GB, 비상업 연구 라이선스) |
| LG 휴머노이드 에셋 | G1 대신 실제 대상 로봇 | 미도착. 오면 `--robot-usd`(재생)와 GMR 등록(리타게팅)이 필요 |

공개 샘플의 라이선스는 `data/raw/*/SOURCE.md`에 있습니다. CMU만 공개 데이터셋에 쓸 수 있고, LAFAN1과 Unitree csv(CC BY-NC-ND)는 내부 검증용입니다.

## 8. 재현 확인

```powershell
conda activate k-humanoid
python -m pytest tests                     # 2026-10-19: 68 passed (G1 에셋, AMASS·SMPL-X 파일, Blender·FBX 샘플이 없으면 해당 테스트만 skip)
python -c "import mink, mujoco; from khumanoid import gmr; print(mujoco.__version__, gmr.GMR_COMMIT[:7])"   # 3.11.0 bb1bbe4
python tools\retarget.py data\raw\cmu_bvh\02_01.bvh --smooth 6 --out-dir $env:TEMP\khumanoid_check
#   -> 86 frames @ 30 fps, residual feet 약 0.66 cm
$env:OMNI_KIT_ACCEPT_EULA = "YES"
python tools\isaac_replay.py --human data\raw\cmu_bvh\02_01.bvh --robot-motion $env:TEMP\khumanoid_check\02_01_g1.npz --headless --check-out $env:TEMP\khumanoid_check
#   -> $env:TEMP\khumanoid_check\02_01_sim_check.json: human_qc / robot_qc 모두 PASS
python tools\isaac_replay.py --robot-motion $env:TEMP\khumanoid_check\02_01_g1.npz --physics --check-out $env:TEMP\khumanoid_check
#   -> $env:TEMP\khumanoid_check\02_01_g1_sim.json / _sim.npz: 넘어짐 0, 관절 추종 RMSE 중앙값 약 0.4°
```
