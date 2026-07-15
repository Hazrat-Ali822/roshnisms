@echo off
REM Daily: auto late fee on overdue challans + refresh fee statuses.
cd /d "%~dp0.."
call venv\Scripts\activate
python manage.py fees_daily
