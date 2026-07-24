@echo off
title SnackQ - Smart Canteen

cd /d "%~dp0"

call .venv\Scripts\activate

echo =====================================
echo        SnackQ Smart Canteen
echo =====================================
echo.

python app.py

pause