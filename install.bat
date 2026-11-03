@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Cai dat Dich Truyen Tranh v2.0 by Duy Anh

rem ---------- 1. Kiem tra Python ----------
where python >nul 2>nul
if errorlevel 1 (
  echo [LOI] Chua cai Python. Hay cai Python 3.11 hoac 3.12 tu python.org
  echo       ^(nho tick "Add python.exe to PATH" khi cai^)
  pause & exit /b 1
)
python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)"
if errorlevel 1 (
  echo [LOI] Can Python 3.10 - 3.13. Phien ban hien tai:
  python --version
  echo       Khuyen dung Python 3.11 hoac 3.12.
  pause & exit /b 1
)

rem ---------- 2. Tu nhan GPU NVIDIA ----------
set "TORCH_IDX=cpu"
set "GPU_NAME="
set "CC_MAJOR="
where nvidia-smi >nul 2>nul
if not errorlevel 1 (
  for /f "usebackq delims=" %%g in (`nvidia-smi --query-gpu^=name --format^=csv^,noheader 2^>nul`) do if not defined GPU_NAME set "GPU_NAME=%%g"
  for /f "usebackq tokens=1 delims=." %%a in (`nvidia-smi --query-gpu^=compute_cap --format^=csv^,noheader 2^>nul`) do if not defined CC_MAJOR set "CC_MAJOR=%%a"
)
rem RTX 20xx tro len (compute >= 7) -> CUDA 12.8 ; GTX 9xx/10xx/16xx -> CUDA 12.6
if defined GPU_NAME set "TORCH_IDX=cu126"
if defined GPU_NAME if defined CC_MAJOR if !CC_MAJOR! GEQ 7 set "TORCH_IDX=cu128"
if defined GPU_NAME if defined CC_MAJOR if !CC_MAJOR! LSS 5 set "TORCH_IDX=cpu"
if defined GPU_NAME if not defined CC_MAJOR echo %GPU_NAME%| findstr /i /c:"RTX 50" >nul && set "TORCH_IDX=cu128"
rem Cho phep ep che do: install.bat cpu  /  install.bat cu126  /  install.bat cu128
if not "%~1"=="" set "TORCH_IDX=%~1"

echo.
if defined GPU_NAME (
  echo Tim thay GPU: !GPU_NAME!  ^(compute !CC_MAJOR!^)
) else (
  echo Khong tim thay GPU NVIDIA - se cai ban CPU.
)
echo Ban PyTorch se cai: !TORCH_IDX!
echo.

rem ---------- 3. Moi truong ao ----------
if not exist venv\Scripts\python.exe (
  echo Tao moi truong ao venv...
  python -m venv venv || (echo [LOI] Khong tao duoc venv & pause & exit /b 1)
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip

rem Neu da co PyTorch ban CPU ma may co GPU -> go ra de cai ban GPU
if not "!TORCH_IDX!"=="cpu" (
  python -c "import torch,sys; sys.exit(0 if torch.version.cuda else 1)" >nul 2>nul
  if errorlevel 1 pip uninstall -y torch torchvision >nul 2>nul
)

rem ---------- 4. PyTorch ----------
pip install torch torchvision --index-url https://download.pytorch.org/whl/!TORCH_IDX!
if errorlevel 1 (echo [LOI] Cai PyTorch that bai & pause & exit /b 1)

rem Khoa phien ban torch de cac thu vien khac khong thay bang ban CPU
pip freeze > "%TEMP%\mdv_freeze.txt"
findstr /b /i /c:"torch==" /c:"torchvision==" "%TEMP%\mdv_freeze.txt" > venv\constraints.txt

rem ---------- 5. Thu vien con lai ----------
pip install -r requirements.txt -c venv\constraints.txt
if errorlevel 1 (echo [LOI] Cai thu vien that bai & pause & exit /b 1)

echo.
python -c "import torch;print('=> GPU san sang:', torch.cuda.get_device_name(0)) if torch.cuda.is_available() else print('=> App se chay bang CPU')"
echo.
rem ---------- 6. Loi tat ngoai Desktop (co icon) ----------
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Dich Truyen Tranh.lnk'); $s.TargetPath='%~dp0venv\Scripts\pythonw.exe'; $s.Arguments='\"%~dp0main.py\"'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0icon.ico'; $s.Save()" >nul 2>nul
echo Da tao loi tat "Dich Truyen Tranh" ngoai Desktop.
echo Cai dat xong! Mo app bang loi tat ngoai Desktop hoac run.bat
echo (Lan dich dau tien app tu tai model OCR va model dich ve may, can Internet.)
pause
