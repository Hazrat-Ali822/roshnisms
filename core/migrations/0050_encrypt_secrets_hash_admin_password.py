"""Data migration: protect at-rest credentials on existing rows.

Runs per-database (master registry + every tenant .sqlite3 via migrate_tenants):
  * hashes any legacy plaintext School.admin_password (one-way), and
  * re-saves the gateway/SMS secret fields so EncryptedCharField encrypts them.

Everything is tolerant: an already-hashed password is left alone, and the
secret fields decrypt-on-read (returning legacy plaintext unchanged) then
encrypt-on-save, so running this once per DB is safe and idempotent.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    School = apps.get_model('core', 'School')
    db = schema_editor.connection.alias
    try:
        from core.crypto import hash_password, is_hashed
    except Exception:
        return  # crypto/cryptography unavailable — leave data as-is

    for s in School.objects.using(db).all():
        if s.admin_password and not is_hashed(s.admin_password):
            s.admin_password = hash_password(s.admin_password)
        # Saving encrypts the EncryptedCharField secret fields (their current
        # in-memory values were decrypted/passed-through on read).
        s.save(using=db)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0049_alter_school_pay_easypaisa_hash_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
