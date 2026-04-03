@echo off
setlocal enabledelayedexpansion

:: MesVols - Watchdog local (monitoring/verification)
:: Ne modifie pas le CSV ni data.js, ne push pas.
:: GitHub Actions est le pipeline de publication.

cd /d "%~dp0"

:: Dossier de logs
if not exist "logs" mkdir logs

:: Fichier log du jour
set LOG=logs\run_%date:~-4%%date:~-7,2%%date:~-10,2%.log

:: Horodatage
for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t

echo. >> "%LOG%"
echo ========================================== >> "%LOG%"
echo [%NOW%] Watchdog MesVols >> "%LOG%"
echo ========================================== >> "%LOG%"

python watchdog.py >> "%LOG%" 2>&1
set EC=!errorlevel!

for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
if !EC! neq 0 (
    echo [!NOW!] Watchdog termine avec erreur (code !EC!) >> "%LOG%"
) else (
    echo [!NOW!] Watchdog OK >> "%LOG%"
)

exit /b !EC!
