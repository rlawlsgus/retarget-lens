# 릴리즈 올리기 (GitHub Releases)

빌드한 RetLens를 GitHub 저장소(`rlawlsgus/retarget-lens`)의 Releases에 zip으로 올리는 순서입니다. 받는 사람은 zip을 풀고 `RetLens.exe`를 실행하면 됩니다. 무엇이 들어가는지는 [packaging.md](packaging.md)에 있습니다.

## 순서

### 1. 버전 정하기

`khumanoid/__init__.py`의 `__version__`을 올립니다(예: `"0.1.0"` → `"0.2.0"`). 태그는 `v` + 버전(`v0.2.0`)으로 씁니다.

- 0.x는 아직 시험판이라는 뜻입니다. 기능이 바뀌면 가운데 숫자, 고치기만 했으면 끝 숫자를 올립니다.
- 같은 버전 번호로 다시 올리지 않습니다. 고칠 것이 생기면 번호를 올려 새로 만듭니다.

### 2. 테스트와 빌드

```powershell
conda activate k-humanoid
python -m pytest tests
powershell -ExecutionPolicy Bypass -File scripts\build_retlens.ps1 -Samples    # -> dist\RetLens\ (약 4분)
```

- `-Samples`는 CMU 샘플(BVH·C3D, 재배포 가능)을 넣습니다. AMASS·LAFAN1·SMPL-X 모델 같은 라이선스 제한 파일은 빌드에 들어가지 않습니다(`tests/test_stage_resources.py`).
- 빌드한 프로그램을 한 번 실행해 봅니다. conda를 쓰지 않는 새 PowerShell 창에서 `dist\RetLens\RetLens.exe dist\RetLens\_internal\samples\cmu_bvh\02_01.bvh`로 열어 3D와 분석 표가 나오는지, "도움말 > 정보"의 버전이 맞는지 봅니다.

### 3. zip과 체크섬 만들기

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1
```

- `dist\RetLens-<버전>-win64.zip`(그 안에 `RetLens\` 폴더 하나)과 `dist\RetLens-<버전>-win64.zip.sha256`이 생깁니다.
- 빌드의 `retlens-cli.exe info`가 알려 주는 버전이 `__version__`과 다르면 멈춥니다(옛 빌드를 올리는 실수 방지). 같은 버전 zip을 다시 만들 때는 `-Force`입니다.
- GitHub 릴리즈 파일은 하나에 2 GiB 미만이어야 합니다. 지금 빌드는 풀었을 때 약 1.2 GB, zip은 약 0.5 GB입니다.

### 4. 코드 커밋·푸시 (GitHub Desktop)

릴리즈 태그는 커밋을 가리키므로, 그 빌드를 만든 코드가 먼저 GitHub에 있어야 합니다.

1. GitHub Desktop에서 이 저장소를 열고, 바뀐 파일을 확인해 요약(예: `RetLens 0.2.0`)을 적고 **Commit to main**을 누릅니다.
2. **Push origin**을 누릅니다.
3. `data/`, `reports/`, `models/`, `build/`, `dist/`, `docs/internal/`은 `.gitignore`에 있어서 올라가지 않습니다. 변경 목록에 데이터 파일이나 문서(pptx, pdf)가 보이면 커밋하지 마세요.

### 5. GitHub에서 릴리즈 만들기 (웹)

1. 브라우저에서 `https://github.com/rlawlsgus/retarget-lens/releases/new`를 엽니다(저장소 페이지 오른쪽 **Releases** → **Draft a new release**).
2. **Choose a tag**에 `v0.2.0`을 입력하고 **Create new tag: v0.2.0 on publish**를 고릅니다. **Target**은 `main`입니다.
3. **Release title**: `RetLens 0.2.0`.
4. 설명에 아래 "릴리즈 노트 틀"을 채워 넣습니다.
5. 아래 **Attach binaries** 칸에 `dist\RetLens-0.2.0-win64.zip`과 `.zip.sha256`을 끌어다 놓고, 업로드가 끝날 때까지 기다립니다(0.5 GB라 몇 분 걸릴 수 있음).
6. 시험판이면 **Set as a pre-release**를 켭니다. 처음 몇 번은 켜 두는 것을 권합니다(아래 "알아 둘 것"의 라이선스 고지).
7. **Publish release**를 누릅니다. 바로 올리지 않으려면 **Save draft**로 두었다가 나중에 Publish합니다.

GitHub가 저장소 소스 zip(**Source code**)을 자동으로 붙입니다. 데이터는 git에 없으므로 들어가지 않습니다.

### 6. 확인

- 릴리즈 페이지에서 zip을 받아, 다른 폴더(가능하면 다른 PC)에 풀고 `RetLens.exe`를 실행해 봅니다.
- 받은 파일의 해시가 `.sha256`과 같은지 봅니다.

```powershell
Get-FileHash RetLens-0.2.0-win64.zip -Algorithm SHA256
```

## 릴리즈 노트 틀

```markdown
## RetLens 0.2.0

사람 모캡(BVH·FBX·AMASS SMPL-X·C3D)을 Unitree G1에 리타게팅해 보고, 비교하고, Isaac Sim 물리로 검증하는 Windows 프로그램입니다.

### 설치
1. `RetLens-0.2.0-win64.zip`을 받아 원하는 폴더에 풉니다.
2. `RetLens\RetLens.exe`를 실행합니다. "Windows의 PC 보호" 창이 뜨면 "추가 정보 > 실행"을 누릅니다(코드 서명 전).
3. FBX·SMPL-X·물리 기능은 "파일 > 환경 설정"에서 Blender 4.5, SMPL-X 모델 폴더, Isaac Sim 6.1을 지정하면 켜집니다.

### 바뀐 점
- ...

### 요구 사항
- Windows 10/11 64비트, WebGL이 되는 GPU
- 물리·동영상: NVIDIA RTX GPU, Isaac Sim 6.1 (NVIDIA EULA 동의 필요)

SHA-256: `<.sha256 파일의 값>`
```

## 알아 둘 것

- **저장소 공개 범위:** 저장소가 비공개(private)면 릴리즈도 저장소 권한이 있는 사람만 받을 수 있습니다. 외부에 나눠 주려면 저장소를 공개하거나, 받는 사람을 협업자로 추가합니다.
- **라이선스 고지:** 지금 빌드에는 GMR(MIT)·Unitree G1(BSD-3) 고지만 들어 있습니다. Qt·WebEngine(LGPL/BSD) 같은 제3자 고지 묶음은 설치 파일 단계에서 넣을 예정이라([packaging.md](packaging.md) "남은 일"), 그 전까지는 내부·시험 배포(pre-release)로 쓰는 것이 안전합니다.
- **SmartScreen:** 서명하지 않은 exe라 처음 실행할 때 경고가 뜹니다. 공개 배포라면 코드 서명 인증서가 필요합니다.
- **올리면 안 되는 것:** AMASS·LAFAN1·Unitree csv와 그 파생물(리타겟, 리포트, 영상), SMPL-X 모델 파일, `docs/internal/`의 내부 문서. 빌드와 git 설정이 이미 막고 있지만, 릴리즈에 파일을 직접 더할 때 주의하세요([data.md](data.md)).
- **명령줄로 올리기 (선택):** GitHub CLI(`gh`)를 설치하고 로그인했다면 5단계를 한 줄로 할 수 있습니다. 위 "릴리즈 노트 틀"을 채워 `dist\notes.md`로 저장한 뒤 실행합니다.

```powershell
gh release create v0.2.0 dist\RetLens-0.2.0-win64.zip dist\RetLens-0.2.0-win64.zip.sha256 --title "RetLens 0.2.0" --notes-file dist\notes.md --prerelease
```
