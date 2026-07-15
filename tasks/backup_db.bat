@echo off
REM Daily: back up the SQLite database into backups\ (keeps the most recent 30).
cd /d "%~dp0.."
call venv\Scripts\activate
python manage.py backup_db
