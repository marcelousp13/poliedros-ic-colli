@echo off
chcp 65001 >nul
setlocal
title Atlas Computacional de Poliedros — IC com Colli (IME-USP)

set "SCRIPT_DIR=%~dp0"
set "PY_EXE="

if exist "%LOCALAPPDATA%\spyder-6\envs\spyder-runtime\python.exe" (
    set "PY_ENV=%LOCALAPPDATA%\spyder-6\envs\spyder-runtime"
    set "PY_EXE=%LOCALAPPDATA%\spyder-6\envs\spyder-runtime\python.exe"
    set "PATH=%LOCALAPPDATA%\spyder-6\envs\spyder-runtime\Library\bin;%LOCALAPPDATA%\spyder-6\envs\spyder-runtime\DLLs;%LOCALAPPDATA%\spyder-6\envs\spyder-runtime;%PATH%"
) else (
    for %%P in (python.exe python3.exe) do (
        where %%P >nul 2>&1 && (
            set "PY_EXE=%%P"
            goto :found
        )
    )
)

:found
if "%PY_EXE%"=="" (
    echo [ERRO] Interpretador Python com numpy/scipy/networkx nao encontrado.
    pause
    exit /b 1
)

echo Iniciando servidor cientifico local com: "%PY_EXE%"
"%PY_EXE%" "%SCRIPT_DIR%server.py" --port 8765 --open
pause
