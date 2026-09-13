@echo off
setlocal
cd /d "%~dp0"
title VideoTranscriber

if exist "%~dp0runtime\node\bin\node.exe" set "PATH=%~dp0runtime\bin\fallback;%~dp0runtime\node\bin;%PATH%"
if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"

echo.
echo ========================================
echo       VideoTranscriber
echo ========================================
echo.

where git >nul 2>&1
if errorlevel 1 goto missing_git
where uv >nul 2>&1
if errorlevel 1 goto missing_uv

set "PNPM=pnpm"
where pnpm >nul 2>&1
if errorlevel 1 (
  where corepack >nul 2>&1
  if errorlevel 1 goto missing_pnpm
  set "PNPM=corepack pnpm"
)

call %PNPM% --version >nul 2>&1
if errorlevel 1 goto broken_pnpm

if not exist ".env" copy /Y ".env.example" ".env" >nul
if not exist "apps\web\.env" copy /Y "apps\web\.env.example" "apps\web\.env" >nul

if not exist "services\cobalt\api\package.json" (
  echo Descargando el componente de TikTok...
  git clone --depth 1 https://github.com/imputnet/cobalt.git "services\cobalt"
  if errorlevel 1 goto startup_error
)

if not exist "services\cobalt\api\.env" (
  >"services\cobalt\api\.env" echo API_URL=http://localhost:9187/
  >>"services\cobalt\api\.env" echo API_PORT=9187
  >>"services\cobalt\api\.env" echo API_LISTEN_ADDRESS=127.0.0.1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo Instalando el motor de transcripcion...
  uv sync --project backend
  if errorlevel 1 goto startup_error
)

if not exist "node_modules" (
  echo Instalando la interfaz...
  call %PNPM% install --frozen-lockfile
  if errorlevel 1 goto startup_error
)

if not exist "services\cobalt\node_modules" (
  echo Instalando el componente de TikTok...
  call %PNPM% --dir services\cobalt install --frozen-lockfile
  if errorlevel 1 goto startup_error
)

if /I "%~1"=="--check" (
  echo Todo esta preparado para iniciar.
  exit /b 0
)

echo Iniciando. Esta ventana debe permanecer abierta.
echo Para detener la aplicacion, pulsa Ctrl+C o cierra esta ventana.
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:5187/'"
call %PNPM% dev
exit /b %errorlevel%

:missing_git
echo ERROR: falta Git. Instalalo desde https://git-scm.com/download/win
goto requirements_error

:missing_uv
echo ERROR: falta uv. Instalalo desde https://docs.astral.sh/uv/getting-started/installation/
goto requirements_error

:missing_pnpm
echo ERROR: faltan pnpm y Corepack. Reinstala Node.js LTS desde https://nodejs.org/
goto requirements_error

:broken_pnpm
echo ERROR: no se pudo preparar pnpm con Corepack.
echo Comprueba la conexion a Internet y vuelve a intentarlo.
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
