@echo off
REM Monthly (run on the 1st): create this month's challans for active students.
cd /d "%~dp0.."
call venv\Scripts\activate
python manage.py fees_generate
