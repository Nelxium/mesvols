@echo off
setlocal enabledelayedexpansion

:: MesVols - Pipeline automatise
:: Lance scraping + publication + push GitHub Pages

cd /d "%~dp0"

:: Dossier de logs
if not exist "logs" mkdir logs

:: Fichier log du jour
set LOG=logs\run_%date:~-4%%date:~-7,2%%date:~-10,2%.log

:: Horodatage
for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t

echo. >> "%LOG%"
echo ========================================== >> "%LOG%"
echo [%NOW%] Debut du pipeline >> "%LOG%"
echo ========================================== >> "%LOG%"

:: Etape 1 : Scraping + generation data.js
echo [%NOW%] Etape 1/3 : python main.py >> "%LOG%"
python main.py >> "%LOG%" 2>&1
if !errorlevel! neq 0 (
    for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
    echo [!NOW!] ECHEC main.py (code !errorlevel!) >> "%LOG%"
    exit /b 1
)
for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
echo [!NOW!] main.py OK >> "%LOG%"

:: Etape 2 : Publication vers docs/
echo [!NOW!] Etape 2/3 : python publish.py >> "%LOG%"
python publish.py >> "%LOG%" 2>&1
if !errorlevel! neq 0 (
    for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
    echo [!NOW!] ECHEC publish.py (code !errorlevel!) >> "%LOG%"
    exit /b 2
)
for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
echo [!NOW!] publish.py OK >> "%LOG%"

:: Etape 3 : Commit + push si changements
echo [!NOW!] Etape 3/3 : git commit + push >> "%LOG%"
git add data.js prix_vols.csv docs/data.js >> "%LOG%" 2>&1

git diff --cached --quiet
if !errorlevel! equ 0 (
    for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
    echo [!NOW!] Aucun changement a publier >> "%LOG%"
    exit /b 0
)

for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
git commit -m "update data %NOW%" >> "%LOG%" 2>&1
if !errorlevel! neq 0 (
    echo [!NOW!] ECHEC git commit >> "%LOG%"
    exit /b 3
)

git push >> "%LOG%" 2>&1
if !errorlevel! neq 0 (
    for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
    echo [!NOW!] ECHEC git push >> "%LOG%"
    exit /b 4
)

for /f "tokens=*" %%t in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set NOW=%%t
echo [!NOW!] Push OK — pipeline termine avec succes >> "%LOG%"
exit /b 0
