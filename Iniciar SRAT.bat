@echo off
setlocal
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"

cd /d "%PROJECT_DIR%"

if not defined DB_HOST set "DB_HOST=localhost"
if not defined DB_USER set "DB_USER=root"
if not defined DB_PASSWORD set "DB_PASSWORD="
if not defined DB_NAME set "DB_NAME=srat_db"
if not defined DB_PORT set "DB_PORT=3306"

if not exist "%PYTHON%" (
	echo No se encontro el entorno Python del proyecto:
	echo %PYTHON%
	pause
	exit /b 1
)

powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
	start "SRAT Backend" /min "%PYTHON%" -m uvicorn main:app --host 127.0.0.1 --port 8000
)

for /l %%i in (1,1,30) do (
	powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"
	if not errorlevel 1 goto backend_ready
	powershell -NoProfile -Command "Start-Sleep -Seconds 1"
)

echo No fue posible iniciar el backend en el puerto 8000.
echo Revisa la ventana SRAT Backend para ver el error.
pause
exit /b 1

:backend_ready
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5501/Frontend.html' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
	start "SRAT Frontend" /min "%PYTHON%" -m http.server 5501 --bind 127.0.0.1 --directory "%CD%"
)

for /l %%i in (1,1,10) do (
	powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5501/Frontend.html' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"
	if not errorlevel 1 goto frontend_ready
	powershell -NoProfile -Command "Start-Sleep -Seconds 1"
)

echo No fue posible iniciar el frontend en el puerto 5501.
pause
exit /b 1

:frontend_ready
start "" "http://127.0.0.1:5501/Frontend.html"

endlocal