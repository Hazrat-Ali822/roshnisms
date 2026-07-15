@echo off
REM Weekly: SMS a fee reminder to every defaulter guardian.
cd /d "%~dp0.."
call venv\Scripts\activate
python manage.py fees_remind
