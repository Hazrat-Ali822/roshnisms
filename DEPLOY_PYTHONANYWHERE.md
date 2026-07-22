# Deploying & testing on PythonAnywhere (+ killing the delay)

This guide gets Roshni SMS running fast on PythonAnywhere. **If the site feels
slow, 90% of the time it is the three "Speed" steps below — do those.**

---

## A. First-time setup

1. **Upload the code** — easiest is Git. In a PythonAnywhere **Bash console**:
   ```bash
   git clone https://github.com/Hazrat-Ali822/roshnisms.git roshni_sms
   cd roshni_sms
   ```
2. **Virtualenv + install**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Database + static**:
   ```bash
   python manage.py migrate
   python manage.py setup_school        # blank real school (admin/admin123)
   python manage.py collectstatic --noinput
   ```
4. **Web tab → Add a new web app → Manual configuration** (matching your Python
   version). Then set:
   - **Source code:** `/home/<you>/roshni_sms`
   - **Virtualenv:** `/home/<you>/roshni_sms/.venv`
   - **WSGI file:** edit it (see step B) so it points at `roshni.wsgi`.

---

## B. WSGI file — the env vars that make it FAST

Web tab → click the **WSGI configuration file** link and make it look like this
(replace `<you>`):

```python
import os, sys

path = '/home/<you>/roshni_sms'
if path not in sys.path:
    sys.path.insert(0, path)

# ---- Performance / production settings (THIS removes most of the delay) ----
os.environ['ROSHNI_DEBUG'] = '0'                       # cache templates, fast static
os.environ['ROSHNI_ALLOWED_HOSTS'] = '<you>.pythonanywhere.com'
os.environ['ROSHNI_HTTPS'] = '1'                       # PA serves HTTPS

from roshni.wsgi import application
```

> **Why `ROSHNI_DEBUG=0` matters most:** with DEBUG on (the offline default),
> Django re-reads every template from disk on every request and serves static
> files the slow way. `DEBUG=0` turns on template caching and lets WhiteNoise
> serve pre-compressed files — this alone makes the whole site feel snappy.

---

## C. Three "Speed" steps (do all three)

**1. Turn off DEBUG** — done in the WSGI file above (`ROSHNI_DEBUG=0`).

**2. Map static files so PythonAnywhere serves them directly** (not the Python
worker). Web tab → **Static files** section → add:

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/<you>/roshni_sms/staticfiles` |

This is huge: without it, every CSS/JS/font/image goes through your one Python
worker and queues behind page requests. With it, PA's fast file server handles
them and the worker only does real pages.

**3. Re-collect compressed static after every deploy:**
```bash
python manage.py collectstatic --noinput
```
The project is set up (WhiteNoise `CompressedStaticFilesStorage`) to pre-build
`.gz`/`.br` versions, so assets download much smaller.

**Then always finish with a reload:** Web tab → big green **Reload** button (or
`touch /var/www/<you>_pythonanywhere_com_wsgi.py`).

---

## D. Updating after a change (routine deploy)

```bash
cd ~/roshni_sms
source .venv/bin/activate
git pull origin main
python manage.py migrate                  # if migrations changed
python manage.py collectstatic --noinput  # if static/CSS changed
# then Web tab → Reload
```

---

## E. What delay is "normal" vs fixable

| Symptom | Cause | Fix |
|---|---|---|
| **Every page slow** | DEBUG on / static through worker | Steps C1 + C2 (the big win) |
| **First hit slow, then fine** | Free-tier worker "cold start" — it sleeps when idle and reloads | Expected on the free tier. A **paid** tier keeps it always-warm. Hitting the site regularly (or an uptime pinger) helps. |
| **Slow once a day** | The daily jobs (late fees, reminders) run on the first request of the day | Normal; runs once. On paid tiers you can move it to a scheduled task. |
| **A specific button is slow/hangs** | Free tier **blocks outbound internet** except a whitelist — so live SMS / payment gateway / web-push calls time out | Keep those in "console/test" mode on free tier, or upgrade + whitelist the provider. (The UI itself has **no** external calls — fonts & Chart.js are self-hosted.) |

> Free-tier CPU is limited (CPU-seconds/day). If you hit the quota the site
> throttles. For real load/marketing, use a **paid** plan (always-on worker,
> more CPU, whitelisted internet).

---

## F. Load-testing the LIVE PythonAnywhere site

Run this **from your own computer** (not inside PA), pointing at your PA URL:

```bash
pip install -r requirements-dev.txt
locust --host https://<you>.pythonanywhere.com
# browser: http://localhost:8089 → Users 20, Ramp 5 → Start
# (set ROSHNI_LOAD_USER / ROSHNI_LOAD_PASS to a real login for signed-in pages)
```

Watch the response-time graph. Free tier will plateau at a low number of users
(one worker); that is the platform, not the code. Compare before/after the Speed
steps in section C — you should see a clear drop in response time.

See **TESTING.md** for the full testing guide.
