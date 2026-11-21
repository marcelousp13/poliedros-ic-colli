@echo off
chcp 65001 >nul
setlocal
title Importar Pasta Local para o Site (Protocolo de 4 Passos - IC com Colli)

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

if not "%~1"=="" (
    "%PY_EXE%" "%SCRIPT_DIR%importar_solidos.py" "%~1" --aplicar
    pause
    exit /b 0
)

echo ============================================================================
echo   IMPORTADOR CIENTIFICO DE 4 PASSOS — ATLAS DE POLIEDROS (IME-USP)
echo ============================================================================
set /p "TARGET_DIR=Cole o caminho da pasta local (Enter = pasta solidos/ padrao): "
if "%TARGET_DIR%"=="" (
    "%PY_EXE%" "%SCRIPT_DIR%importar_solidos.py" --aplicar
) else (
    "%PY_EXE%" "%SCRIPT_DIR%importar_solidos.py" "%TARGET_DIR%" --aplicar
)
pause
