"""Security primitives for at-rest credential protection.

Two concerns live here:

1. **Reversible field encryption** — API secrets (SMS/WhatsApp tokens, payment
   gateway passwords/salts) must be readable at runtime to sign requests, so
   they cannot be hashed; instead they are encrypted at rest with Fernet
   (AES-128-CBC + HMAC). ``EncryptedCharField`` makes this transparent: values
   are encrypted on the way into the database and decrypted on the way out, so
   call-sites keep using plain strings.

2. **One-way password hashing helpers** — the SaaS registry stores each school's
   admin password only so a wiped/rebuilt tenant database can recreate a working
   admin login. We store a Django password *hash* (never plaintext) and, when
   rebuilding, assign that hash straight onto the new ``User`` row.

Both are decrypt-/detect-*tolerant*: a value that is not (yet) encrypted or not
a recognised hash is passed through unchanged, so the migration rollout and any
legacy row can never break login or gateway calls.
"""
from django.conf import settings
from django.db import models

# Marks a value this module encrypted, so decrypt() can tell ciphertext from a
# legacy plaintext value and stay idempotent.
_PREFIX = 'enc::'


def _fernet():
    """Build a Fernet from settings.FIELD_ENCRYPTION_KEY (lazily, so importing
    this module never hard-requires cryptography until encryption is used)."""
    from cryptography.fernet import Fernet
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
    if not key:
        raise RuntimeError('FIELD_ENCRYPTION_KEY is not configured.')
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt(text):
    """Encrypt a string for storage. Empty/blank values are stored as-is."""
    if text is None or text == '':
        return text
    if isinstance(text, str) and text.startswith(_PREFIX):
        return text  # already encrypted — don't double-wrap
    token = _fernet().encrypt(str(text).encode()).decode()
    return _PREFIX + token


def decrypt(text):
    """Decrypt a stored value. A value without our prefix (legacy plaintext) or
    one that fails to decrypt is returned unchanged, so nothing ever breaks."""
    if not text or not isinstance(text, str) or not text.startswith(_PREFIX):
        return text
    try:
        return _fernet().decrypt(text[len(_PREFIX):].encode()).decode()
    except Exception:
        return text


class EncryptedCharField(models.CharField):
    """A CharField whose value is encrypted at rest and decrypted on load.

    The column stays a normal varchar (SQLite ignores the length anyway), so no
    special database support is needed. Because encryption enlarges the value,
    give these fields a generous max_length in the model.
    """

    def from_db_value(self, value, expression, connection):
        return decrypt(value)

    def to_python(self, value):
        return decrypt(super().to_python(value))

    def get_prep_value(self, value):
        return encrypt(super().get_prep_value(value))


# ---------------------------------------------------------------------------
# Password-hash helpers (for the SaaS admin credential on the School registry)
# ---------------------------------------------------------------------------

def hash_password(raw):
    """Return a Django password hash for a plaintext value ('' stays '')."""
    if not raw:
        return ''
    from django.contrib.auth.hashers import make_password
    return make_password(raw)


def is_hashed(value):
    """True if value is already a recognised Django password hash."""
    if not value:
        return False
    from django.contrib.auth.hashers import identify_hasher
    try:
        identify_hasher(value)
        return True
    except Exception:
        return False


def apply_stored_password(user, stored):
    """Give ``user`` the password represented by ``stored`` (a School's saved
    admin credential). If it is already a hash, assign it directly (no
    re-hashing); if it is legacy plaintext, hash it via set_password. The caller
    is responsible for saving the user."""
    if is_hashed(stored):
        user.password = stored
    else:
        user.set_password(stored or '')
