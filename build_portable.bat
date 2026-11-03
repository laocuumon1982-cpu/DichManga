@echo off
rem Tao ban Portable cua Dich Truyen Tranh (goi tools\build_portable.ps1)
rem   build_portable.bat            : tu nhan GPU, hoi tai san model
rem   build_portable.bat cpu        : ep ban CPU  (cu126 / cu128 de ep ban GPU)
rem   build_portable.bat app        : chi cap nhat code app vao ban portable da co
cd /d "%~dp0"
title Tao ban Portable - Dich Truyen Tranh v2.0 by Duy Anh
if /i "%~1"=="app" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_portable.ps1" -AppOnly
) else if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_portable.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_portable.ps1" -Torch %~1
)
