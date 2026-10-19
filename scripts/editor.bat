@echo off
rem RetLens, the K-Humanoid motion editor (double-click). Extra arguments go to tools\editor.py,
rem e.g.  scripts\editor.bat data\raw\cmu_bvh\02_01.bvh
cd /d "%~dp0.."
set "CONDA_EXE_PATH="
for %%C in (conda.exe) do set "CONDA_EXE_PATH=%%~$PATH:C"
if not defined CONDA_EXE_PATH if exist "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe" set "CONDA_EXE_PATH=%LOCALAPPDATA%\miniconda3\Scripts\conda.exe"
if not defined CONDA_EXE_PATH if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_EXE_PATH=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined CONDA_EXE_PATH (
  echo conda was not found. Create the k-humanoid environment as described in README.md, then run this again.
  pause
  exit /b 1
)
"%CONDA_EXE_PATH%" run --no-capture-output -n k-humanoid python tools\editor.py %*
if errorlevel 1 pause
