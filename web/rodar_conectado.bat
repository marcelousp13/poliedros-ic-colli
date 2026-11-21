@echo off
chcp 65001 >nul
setlocal
title Rodar standbyalone2.py Conectado ao Atlas (Envio Automatico)

set "SCRIPT_DIR=%~dp0"
set "PY_EXE="
if exist "%LOCALAPPDATA%\spyder-6\envs\spyder-runtime\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\spyder-6\envs\spyder-runtime\python.exe"
    set "PATH=%LOCALAPPDATA%\spyder-6\envs\spyder-runtime\Library\bin;%LOCALAPPDATA%\spyder-6\envs\spyder-runtime\DLLs;%LOCALAPPDATA%\spyder-6\envs\spyder-runtime;%PATH%"
) else (
    for %%P in (python.exe python3.exe) do (where %%P >nul 2>&1 && (set "PY_EXE=%%P" & goto :found))
)
:found
if "%PY_EXE%"=="" (echo Python nao encontrado. & pause & exit /b 1)
"%PY_EXE%" "%SCRIPT_DIR%vigia_resultados.py" --executar-main
pause
