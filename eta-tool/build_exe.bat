@echo off
chcp 65001 >nul
cd /d "%~dp0"
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name ETA-Tool --collect-data tzdata app.py
copy /Y config.example.json dist\ >nul
echo.
echo البرنامج جاهز في فولدر dist\ETA-Tool.exe
pause
