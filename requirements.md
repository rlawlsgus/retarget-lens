# 환경 재현 요구사항

이 프로젝트를 다른 PC에서 그대로 돌리기 위해 필요한 것을 모았습니다. 버전은 2026-10-15에 개발 PC에서 직접 확인한 값입니다. 설치 명령과 사용법은 [README](README.md)에 있습니다.

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
```

- Isaac Sim zip은 `https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.1.0-windows-x86_64.zip`이고 MD5는 `a07968e980072c9ca27b2166443e2d89`입니다. 스크립트가 받기·확인·압축 해제·`post_install.bat`을 처리합니다.
- `post_install.bat`은 GUI 예제 링크만 만듭니다. 관리자 권한이 없어 실패해도 시뮬레이터는 정상입니다.
- 처음 실행할 때 NVIDIA 라이선스(EULA) 동의가 필요합니다. 무인 실행에서는 `OMNI_KIT_ACCEPT_EULA=YES`로 동의합니다.
- 첫 실행은 셰이더 컴파일 때문에 약 2분, 이후에는 약 20초 걸립니다.

## 3. Python 환경 `k-humanoid`

정의는 [environment.yml](environment.yml)이고, 개발 PC에 실제로 설치된 버전은 아래와 같습니다. 같은 패키지 빌드까지 맞추려면 4절의 잠금 파일을 쓰세요.

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
| pytorch (CPU) | 2.10.0 (cpu_mkl) | conda-forge | GMR이 import할 때 요구. GPU 빌드는 필요 없음. 이 빌드 때문에 BLAS가 MKL(mkl 2026.1.0)로 바뀜 |
| mink | 1.3.0 | PyPI | GMR의 differential IK (Apache-2.0). conda-forge에 없음 |
| smplx | 0.1.28 | PyPI | AMASS SMPL-X 경로 전용. 코드가 MPI 비상업 연구 라이선스 |

환경에 들어가는 연결 설정:
- **Isaac Sim 연결 훅** (`setup_env.ps1`이 `etc\conda\activate.d\isaacsim_link.{bat,ps1}`로 설치): `ISAACSIM_PATH`, `CARB_APP_PATH`, `ISAAC_PATH`, `EXP_PATH`를 설정하고 `PYTHONPATH`에 `C:\isaacsim\site`를 붙입니다. 그래서 env의 `python`에서 `from isaacsim import SimulationApp`이 됩니다.
- **GMR 연결** (`install_gmr.ps1`): `Lib\site-packages\gmr_k_humanoid.pth`에 `..\GMR` 경로를 적습니다(`pip install -e`와 같은 효과).
- conda 실행 시 `CONDA_CHANNELS=conda-forge` (아래 6절).

호환성 주의:
- `SimulationApp` 안에서는 Kit의 import 훅이 Isaac에 내장된 numpy·scipy·torch(`omni.isaac.ml_archive`, torch 2.11.0+cu128)를 씁니다. env의 같은 패키지가 Kit 시작 전에 import되면 두 버전이 섞여 확장 로딩이 깨집니다.
- env에 torch가 있으면 `from isaacsim import SimulationApp`이 Kit 시작 전에 env의 torch와 numpy를 불러옵니다. `tools/isaac_replay.py`는 그 import 동안만 torch를 숨겨서 해결합니다. **이 env에서 다른 Isaac 스크립트를 새로 만들 때도 같은 처리가 필요합니다**(isaac_replay.py 상단 참고).
- numpy·scipy·mujoco는 Isaac 내장 버전과 마이너 버전까지 맞춰 두었습니다. 올릴 때는 Isaac Sim 버전과 같이 확인하세요.

## 4. 정확한 재현용 잠금 파일

[environment.lock.txt](environment.lock.txt)는 개발 PC의 conda 패키지 목록을 빌드와 다운로드 URL까지 그대로 담은 파일입니다(`conda list --explicit`, win-64 전용). 같은 빌드로 env를 만들려면 아래처럼 합니다.

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

## 6. 네트워크와 외부 소스

| 호스트 | 용도 | 필요한 때 |
|---|---|---|
| `downloads.isaacsim.nvidia.com` | Isaac Sim zip | 설치 |
| `conda.anaconda.org/conda-forge` | conda 패키지 | env 생성 |
| `pypi.org`, `files.pythonhosted.org` | mink, smplx | env 생성 |
| `api.github.com`, `raw.githubusercontent.com` | GMR 소스(고정 커밋), CMU BVH | `install_gmr.ps1`, `fetch_samples.py` |
| `media.githubusercontent.com` | LAFAN1 zip (Git LFS) | `fetch_samples.py lafan1` |
| `huggingface.co` | Unitree LAFAN1 G1 csv | `fetch_samples.py unitree` |
| `omniverse-content-production.s3-us-west-2.amazonaws.com` | Isaac 로봇 에셋(G1) | Isaac 재생할 때마다 |

- **`repo.anaconda.com`(Anaconda defaults 채널)은 이 네트워크에서 막혀 있습니다**(HTTP 429, 클라이언트 등록 필요). `setup_env.ps1`은 프로세스에 `CONDA_CHANNELS=conda-forge`를 설정하고, environment.yml도 `nodefaults`입니다. `.condarc`는 건드리지 않습니다.
- `install_gmr.ps1`과 `fetch_samples.py`는 파일마다 해시(git blob SHA-1 또는 LFS SHA-256)를 확인합니다.

## 7. 직접 받아야 하는 것 (라이선스 제한)

| 항목 | 필요한 기능 | 받는 곳 / 둘 곳 |
|---|---|---|
| SMPL-X 바디모델 (`SMPLX_NEUTRAL.npz` 등) | AMASS SMPL-X 로딩·리타게팅 | smpl-x.is.tue.mpg.de 등록 후 다운로드 → `models/smplx/`, `--smpl-model-dir models` 또는 `SMPL_MODEL_DIR` |
| SMPL+H 바디모델 | AMASS SMPL+H 로딩 | mano.is.tue.mpg.de → `models/smplh/` |
| LG 휴머노이드 에셋 | G1 대신 실제 대상 로봇 | 미도착. 오면 `--robot-usd`(재생)와 GMR 등록(리타게팅)이 필요 |

공개 샘플의 라이선스는 `data/raw/*/SOURCE.md`에 있습니다. CMU만 공개 데이터셋에 쓸 수 있고, LAFAN1과 Unitree csv(CC BY-NC-ND)는 내부 검증용입니다.

## 8. 재현 확인

```powershell
conda activate k-humanoid
python -m pytest tests                     # 17 passed (GMR이 없으면 GMR이 필요한 3개만 skip)
python -c "import general_motion_retargeting, mujoco, torch; print(mujoco.__version__, torch.__version__)"   # 3.11.0 2.10.0
python tools\retarget.py data\raw\cmu_bvh\02_01.bvh --smooth 6 --out-dir data\retargeted\check
#   -> 86 frames @ 30 fps, residual feet 약 0.66 cm
$env:OMNI_KIT_ACCEPT_EULA = "YES"
python tools\isaac_replay.py --human data\raw\cmu_bvh\02_01.bvh --robot-motion data\retargeted\check\02_01_g1.npz --headless --check-out reports\check
#   -> reports\check\02_01_sim_check.json: human_qc / robot_qc 모두 PASS
```
