@echo off
title Bethuel Sang Portfolio
cd /d "C:\Users\BethuelSang\OneDrive - East African Tea Trade Association\Old Files\Desktop\Portifolio"
echo Installing required packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installation failed. Please review the error above.
  pause
  exit /b 1
)
echo.
echo Starting portfolio...
python -m streamlit run app.py
pause
