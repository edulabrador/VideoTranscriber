@echo off
setlocal
cd /d "%~dp0"
title VideoTranscriber

echo.
echo ========================================
echo       VideoTranscriber
echo ========================================
echo.

where git >nul 2>&1
if errorlevel 1 goto missing_git
where uv >nul 2>&1
if errorlevel 1 goto missing_uv
where pnpm >nul 2>&1
if errorlevel 1 goto missing_pnpm

if not exist ".env" copy /Y ".env.example" ".env" >nul
if not exist "apps\web\.env" copy /Y "apps\web\.env.example" "apps\web\.env" >nul

if not exist "services\cobalt\api\package.json" (
  echo Descargando el componente de TikTok...
  git clone --depth 1 https://github.com/imputnet/cobalt.git "services\cobalt"
  if errorlevel 1 goto startup_error
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo Instalando el motor de transcripcion...
  uv sync --project backend
  if errorlevel 1 goto startup_error
)

if not exist "node_modules" (
  echo Instalando la interfaz...
  call pnpm install --frozen-lockfile
  if errorlevel 1 goto startup_error
)

if not exist "services\cobalt\node_modules" (
  echo Instalando el componente de TikTok...
  call pnpm --dir services\cobalt install --frozen-lockfile
  if errorlevel 1 goto startup_error
)

if /I "%~1"=="--check" (
  echo Todo esta preparado para iniciar.
  exit /b 0
)

echo Iniciando. Esta ventana debe permanecer abierta.
echo Para detener la aplicacion, pulsa Ctrl+C o cierra esta ventana.
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:5173/'"
call pnpm dev
exit /b %errorlevel%

:missing_git
echo ERROR: falta Git. Instalalo desde https://git-scm.com/download/win
goto requirements_error

:missing_uv
echo ERROR: falta uv. Instalalo desde https://docs.astral.sh/uv/getting-started/installation/
goto requirements_error

:missing_pnpm
echo ERROR: falta pnpm. Ejecuta: corepack enable pnpm
goto requirements_error

:startup_error
echo.
echo ERROR: no se pudo preparar o iniciar VideoTranscriber.
pause
exit /b 1

:requirements_error
echo Despues vuelve a hacer doble clic en este archivo.
pause
exit /b 1
