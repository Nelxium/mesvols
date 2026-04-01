@echo off
schtasks /create /tn "MesVols_8h" /tr "python C:\MesVols\main.py" /sc daily /st 08:00 /f
schtasks /create /tn "MesVols_20h" /tr "python C:\MesVols\main.py" /sc daily /st 20:00 /f
echo.
echo Taches planifiees creees avec succes !
echo   - MesVols_8h  : tous les jours a 8h00
echo   - MesVols_20h : tous les jours a 20h00
echo.
schtasks /query /tn "MesVols_8h"
schtasks /query /tn "MesVols_20h"
pause
