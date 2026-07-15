import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# When packaged as a single .exe (PyInstaller), bundled code lives in a
# read-only temp folder — so all WRITABLE data (database, secret key, uploads,
# static, backups) must sit next to the .exe instead. DATA_DIR is that folder.
if getattr(sys, 'frozen', False):
    DATA_DIR = Path(sys.executable).resolve().parent
else:
    DATA_DIR = BASE_DIR

# --- Security (configurable via environment; safe to keep defaults on a
#     trusted school LAN, MUST be set before any public/online deployment) ---
# Set a unique secret per install:  set ROSHNI_SECRET_KEY=... (Windows) /
#   export ROSHNI_SECRET_KEY=...  (Linux)
def _get_secret_key():
    """Use ROSHNI_SECRET_KEY if set; else read/create a stable key in a local
    file so each install has its own unique secret with zero setup."""
    env = os.environ.get('ROSHNI_SECRET_KEY')
    if env:
        return env
    key_file = DATA_DIR / '.secret_key'
    if key_file.exists():
        return key_file.read_text().strip()
    from django.core.management.utils import get_random_secret_key
    key = get_random_secret_key()
    try:
        key_file.write_text(key)
    except OSError:
        pass
    return key


SECRET_KEY = _get_secret_key()

# DEBUG is ON by default so the app runs out-of-the-box on a local PC / LAN.
# For an online/public deployment set  ROSHNI_DEBUG=0  (then serve static files
# and set ROSHNI_ALLOWED_HOSTS).
DEBUG = os.environ.get('ROSHNI_DEBUG', '1') != '0'

# Comma-separated, e.g.  ROSHNI_ALLOWED_HOSTS="school.local,192.168.1.10"
_hosts = os.environ.get('ROSHNI_ALLOWED_HOSTS', '').strip()
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(',') if h.strip()] or ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise serves static files (CSS/JS/images) directly, so the app looks
    # right even with DEBUG off and without a separate web server.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.TenantMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Security: force first-login password change, and idle sign-out.
    'core.middleware.ForcePasswordChangeMiddleware',
    'core.middleware.SessionIdleTimeoutMiddleware',
]

# Sign users out after this many seconds of inactivity (0 = never).
SESSION_IDLE_TIMEOUT = int(os.environ.get('ROSHNI_IDLE_TIMEOUT', str(30 * 60)))

ROOT_URLCONF = 'roshni.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.branding',
                'core.context_processors.nav_children',
                'core.context_processors.notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'roshni.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 6}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Karachi'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
# collectstatic gathers CSS/JS here; WhiteNoise serves them in production.
STATIC_ROOT = DATA_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = DATA_DIR / 'media'

# --- HTTPS hardening: ONLY when explicitly enabled (ROSHNI_HTTPS=1) ---
# A school LAN runs over plain http, so forcing HTTPS/secure cookies there would
# break login. Turn this on only for a real internet deployment behind HTTPS.
if os.environ.get('ROSHNI_HTTPS', '0') == '1':
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_CONTENT_TYPE_NOSNIFF = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# ============================================================
# SMS gateway (Phase 7)
# ------------------------------------------------------------
# SMS_BACKEND options:
#   'console' (default) -- prints/logs each SMS; no network or account needed.
#   'twilio'            -- Twilio REST API.
#   'http'              -- a generic HTTP SMS gateway (common with local PK providers).
#
# Real delivery needs YOUR provider account + outbound internet on the deploy
# machine. Keep 'console' for development; switch + fill credentials to go live.
SMS_BACKEND = 'console'

# Numbers stored locally (e.g. 0300-1234567) get this country code for sending.
SMS_COUNTRY_CODE = '+92'

# --- Twilio (when SMS_BACKEND = 'twilio') ---
SMS_TWILIO_SID = ''
SMS_TWILIO_TOKEN = ''
SMS_TWILIO_FROM = ''        # your Twilio number, e.g. '+12025550123'

# --- Generic HTTP gateway (when SMS_BACKEND = 'http') ---
# Put {to} and {text} where the number and message go; both are URL-encoded.
# Example: 'https://sms.example.pk/send?key=ABC&sender=ROSHNI&to={to}&msg={text}'
SMS_HTTP_URL = ''
SMS_HTTP_METHOD = 'GET'     # 'GET' or 'POST'

# --- Automatic notifications (work through whichever backend is set) ---
SMS_NOTIFY_ON_PAYMENT = True     # send a confirmation when a fee payment is recorded
SMS_NOTIFY_ON_ADMISSION = True   # send a welcome when an applicant is enrolled
SMS_NOTIFY_ON_ABSENT = True      # alert a guardian when a student is marked absent