# MRI2MR Core

This package is for users who already have MATLAB and Docker, but do not have the MRI2MR Python environment.

GitHub clone prerequisite:
- Install Git for Windows with Git LFS, then run `git lfs install` before cloning. The bundled portable Python environment is stored with Git LFS and is downloaded automatically during a normal clone.

Start:
1. Start Docker Desktop.
2. Double-click start_core.bat.

Bundled:
- Portable Python: runtime\python\BrainAAL\python.exe
- MRI2MR WebUI and processing scripts
- SPM source folder: spm
- DICOM tools: dcm2niix_win and dcmtk-3.7.0-win64-dynamic

Not bundled:
- MATLAB Runtime
- MATLAB Runtime installer
- SPM compiled executable

SPM uses full MATLAB through config\app_settings.json:
- SPM_BACKEND = matlab_cli
- MATLAB_EXE = matlab

If MATLAB is not on PATH, edit MATLAB_EXE in config\app_settings.json or set the MATLAB_EXE environment variable before launching.
SynthSeg still uses Docker image pwesp/synthseg:py38.
