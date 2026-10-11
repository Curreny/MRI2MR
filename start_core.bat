@echo off
setlocal

cd /d "%~dp0"

set PYTHONDONTWRITEBYTECODE=1
set PYTHONNOUSERSITE=1
set MRI2MR_CORE_ROOT=%~dp0
set PYTHON_EXE=%~dp0runtime\python\BrainAAL\python.exe
set WEBUI_URL=http://127.0.0.1:8000/

if not exist "%PYTHON_EXE%" (
  echo Portable Python not found:
  echo   %PYTHON_EXE%
  pause
  exit /b 1
)

if "%MATLAB_EXE%"=="" (
  for %%M in (matlab.exe) do set MATLAB_EXE=%%~$PATH:M
)
if "%MATLAB_EXE%"=="" if exist "D:\Matlab\bin\matlab.exe" set MATLAB_EXE=D:\Matlab\bin\matlab.exe
if "%MATLAB_EXE%"=="" (
  for /d %%D in ("C:\Program Files\MATLAB\R*") do if exist "%%~fD\bin\matlab.exe" set MATLAB_EXE=%%~fD\bin\matlab.exe
)

if "%MATLAB_EXE%"=="" (
  echo MATLAB was not found on PATH or in common install locations.
  echo Edit config\app_settings.json and set MATLAB_EXE to your matlab.exe path.
  pause
  exit /b 1
)

docker version >nul 2>nul
if errorlevel 1 (
  echo Docker is not available. Please start Docker Desktop before running SynthSeg modes.
)

rem conda-unpack is a one-time relocation operation.  On this machine it can
rem hang indefinitely, so do not run it during normal WebUI startup.  Set
rem MRI2MR_RUN_CONDA_UNPACK=1 before launching only when the portable Python
rem environment has been moved and needs to be repaired.
if /I "%MRI2MR_RUN_CONDA_UNPACK%"=="1" if exist "%~dp0runtime\python\BrainAAL\Scripts\conda-unpack.exe" (
  "%~dp0runtime\python\BrainAAL\Scripts\conda-unpack.exe"
)

start "" "%WEBUI_URL%"
"%PYTHON_EXE%" -B -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000

pause
