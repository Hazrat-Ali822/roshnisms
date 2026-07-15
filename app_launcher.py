"""Entry point for the packaged .exe (PyInstaller).

Double-clicking the .exe runs this: it prepares the database on first launch,
starts a proper local web server (waitress) and opens the browser. All data is
stored next to the .exe, so nothing is lost between runs.
"""
import os
import sys
import threading
import time
import webbrowser

# Sensible defaults for a local install (can still be overridden by env vars).
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'roshni.settings')
os.environ.setdefault('ROSHNI_DEBUG', '0')
os.environ.setdefault('ROSHNI_ALLOWED_HOSTS', '*')

PORT = 8000


def _prepare():
    """First-run setup — safe to run every launch."""
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)
    try:
        call_command('collectstatic', interactive=False, verbosity=0)
    except Exception:                       # noqa: BLE001 - static is best-effort
        pass
    call_command('ensure_admin', verbosity=1)


def _open_browser():
    time.sleep(2.5)
    try:
        webbrowser.open('http://localhost:%d' % PORT)
    except Exception:                       # noqa: BLE001
        pass


def main():
    print('=' * 60)
    print('   Roshni School Management System')
    print('=' * 60)
    print('Starting up, please wait...')
    _prepare()

    from waitress import serve
    from roshni.wsgi import application

    threading.Thread(target=_open_browser, daemon=True).start()
    print('')
    print('  The system is running.')
    print('  Open a browser at:   http://localhost:%d' % PORT)
    print('  First login:  username  admin   password  admin123')
    print('')
    print('  KEEP THIS WINDOW OPEN. Close it to stop the system.')
    print('=' * 60)
    try:
        serve(application, host='0.0.0.0', port=PORT)
    except OSError as exc:
        print('\nCould not start the server: %s' % exc)
        print('Is the system already running in another window?')
        input('Press Enter to close...')


if __name__ == '__main__':
    main()
