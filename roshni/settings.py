import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# All writable data (database, secret key, uploads, static, backups) lives in
# the project base directory.
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


# --- Field encryption key (for at-rest encryption of gateway/SMS secrets) ---
# Same zero-setup pattern as SECRET_KEY: use ROSHNI_FIELD_KEY if set, else read/
# create a stable key file. Keep this file (and .secret_key) safe and BACK IT UP
# with the database — if it is lost, encrypted secrets (payment/SMS tokens) can
# no longer be decrypted and must be re-entered in Settings. Nothing else breaks.
def _get_field_key():
    env = os.environ.get('ROSHNI_FIELD_KEY')
    if env:
        return env
    key_file = DATA_DIR / '.field_key'
    if key_file.exists():
        return key_file.read_text().strip()
    try:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
    except Exception:
        # cryptography unavailable — encryption is disabled; EncryptedCharField
        # then stores plaintext (decrypt-tolerant), so the app still runs.
        return ''
    try:
        key_file.write_text(key)
    except OSError:
        pass
    return key


FIELD_ENCRYPTION_KEY = _get_field_key()


# --- Web Push (VAPID) keys for browser push notifications ---
# Auto-generated once and stored in .vapid_key (same back-up rules as the other
# keys). VAPID_PUBLIC_KEY is handed to the browser as the applicationServerKey.
def _get_vapid():
    pem = os.environ.get('ROSHNI_VAPID_PRIVATE')
    key_file = DATA_DIR / '.vapid_key'
    if not pem and key_file.exists():
        pem = key_file.read_text()
    if not pem:
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
            priv = ec.generate_private_key(ec.SECP256R1())
            pem = priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()).decode()
            try:
                key_file.write_text(pem)
            except OSError:
                pass
        except Exception:
            return '', ''
    try:
        import base64
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        priv = load_pem_private_key(pem.encode(), password=None)
        raw = priv.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)
        pub = base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    except Exception:
        pub = ''
    return pem, pub


VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY = _get_vapid()
VAPID_CLAIM_EMAIL = os.environ.get('ROSHNI_VAPID_EMAIL', 'mailto:admin@roshni.local')


def _get_assetlinks():
    """Digital Asset Links for the per-school Android (TWA) apps built with
    PWABuilder. One JSON file at /.well-known/assetlinks.json verifies every
    school's app so it opens full-screen (no browser bar). Because all schools
    share one domain, ONE file — a list of {"package": ..., "sha256": [...]}
    entries — covers them all; reuse a single signing key so the fingerprint is
    shared. Set env ROSHNI_TWA_ASSETLINKS to that JSON list once apps are built."""
    raw = os.environ.get('ROSHNI_TWA_ASSETLINKS', '').strip()
    if not raw:
        return []
    try:
        import json
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


TWA_ASSETLINKS = _get_assetlinks()

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
    'core.middleware.TenantDatabaseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.TenantRoutingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Security: force first-login password change, and idle sign-out.
    'core.middleware.ForcePasswordChangeMiddleware',
    'core.middleware.SessionIdleTimeoutMiddleware',
]

# Sign users out after this many seconds of inactivity (0 = never). Default is
# long (30 days) so parents/students/staff on the mobile app stay signed in like
# a normal app — one login, then remembered. Set ROSHNI_IDLE_TIMEOUT lower
# (e.g. 1800 = 30 min) for stricter security on shared office computers.
SESSION_IDLE_TIMEOUT = int(os.environ.get('ROSHNI_IDLE_TIMEOUT', str(30 * 24 * 3600)))
# Keep the login cookie across app/browser restarts, and roll its expiry forward
# on every visit, so an active user is never logged out unexpectedly.
SESSION_COOKIE_AGE = int(os.environ.get('ROSHNI_SESSION_AGE', str(30 * 24 * 3600)))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

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
                'core.context_processors.pwa',
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

# WhiteNoise: pre-compress static files (gzip + brotli) at collectstatic time and
# serve them with proper caching headers. This makes CSS/JS/fonts load much
# faster on a slow host (e.g. PythonAnywhere) than Django's plain static serving,
# and needs no manifest (we already cache-bust with ?v= query strings, so there
# is zero risk of collectstatic failing on a missing reference).
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

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

# Use cookie-based sessions to prevent SessionInterrupted exceptions when switching databases mid-request
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

AUTHENTICATION_BACKENDS = [
    'core.backends.EmailOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

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
# --- Email alerts ---
# Console backend logs emails to the terminal without sending (safe default,
# works offline and in tests). Point this at SMTP on deploy to actually send:
#   EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
#   EMAIL_HOST / EMAIL_PORT / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD / EMAIL_USE_TLS
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'Roshni School <noreply@roshni.local>'
