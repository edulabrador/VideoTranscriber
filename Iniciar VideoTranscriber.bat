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

set /p COBALT_REF=<"scripts\cobalt-ref.txt"
if not exist "services\cobalt\api\package.json" (
  echo Descargando el componente de TikTok...
  git clone --filter=blob:none --no-checkout https://github.com/imputnet/cobalt.git "services\cobalt"
  if errorlevel 1 goto startup_error
  git -C services\cobalt checkout --detach %COBALT_REF%
  if errorlevel 1 goto startup_error
)
for /f %%C in ('git -C services\cobalt rev-parse HEAD') do set "COBALT_INSTALLED=%%C"
if not "%COBALT_INSTALLED%"=="%COBALT_REF%" goto cobalt_version_error

if not exist "services\cobalt\api\.env" (
  >"services\cobalt\api\.env" echo API_URL=http://localhost:9187/
  >>"services\cobalt\api\.env" echo API_PORT=9187
  >>"services\cobalt\api\.env" echo API_LISTEN_ADDRESS=127.0.0.1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo Instalando el motor de transcripcion...
  uv sync --project backend --locked
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

powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 5187,8187,9187 -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 goto ports_in_use

echo Iniciando. Esta ventana debe permanecer abierta.
echo Para detener la aplicacion, pulsa Ctrl+C o cierra esta ventana.
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "for ($i = 0; $i -lt 30; $i++) { try { $web = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5187/' -TimeoutSec 2; $api = Invoke-RestMethod 'http://127.0.0.1:8187/api/health' -TimeoutSec 2; if ($web.StatusCode -eq 200 -and $web.Content -match '<title>VideoTranscriber</title>' -and $api.status -eq 'ok' -and $api.app -eq 'VideoTranscriber') { Start-Process 'http://127.0.0.1:5187/'; break } } catch {}; Start-Sleep -Seconds 1 }"
call %PNPM% dev
exit /b %errorlevel%

:ports_in_use
echo ERROR: uno de los puertos 5187, 8187 o 9187 ya esta ocupado.
echo Cierra la instancia anterior o la aplicacion que utiliza ese puerto.
goto requirements_error

:cobalt_version_error
echo ERROR: la version instalada de Cobalt no coincide con scripts\cobalt-ref.txt.
echo Comprueba los cambios locales de services\cobalt antes de actualizar ese componente.
goto requirements_error

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
