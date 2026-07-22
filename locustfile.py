"""Performance / load testing for Roshni SMS, using Locust.

Locust pretends to be many users hitting the site at once, and measures how
fast the server answers as the crowd grows — so you learn how many concurrent
users one server can hold before it slows down.

--------------------------------------------------------------------
SETUP (one time)
    pip install locust          # or: pip install -r requirements-dev.txt

RUN
    1. Start the app in one terminal (use a REAL server, not autoreload):
           python manage.py runserver 127.0.0.1:8000
    2. In another terminal, start Locust:
           locust                       # reads this file automatically
    3. Open http://localhost:8089 , set:
           Number of users     e.g. 50
           Ramp up (users/sec) e.g. 5
           Host                http://127.0.0.1:8000
       Press "Start" and watch response times + failures live.

    Headless (no browser, for CI / scripts):
        locust --headless -u 50 -r 5 -t 1m --host http://127.0.0.1:8000

CREDENTIALS
    Set a real login the server accepts (defaults shown):
        ROSHNI_LOAD_USER=admin  ROSHNI_LOAD_PASS=admin123  locust ...
    (Demo data uses password 'roshni123'; a fresh real school uses 'admin123'.)

NOTE ON SQLITE
    SQLite serialises writes, so heavy WRITE load (many fee posts at once) will
    bottleneck by design — that is the database, not the app. Read-heavy pages
    (dashboards, lists) reflect real browsing load best. For high write
    concurrency, load-test against PostgreSQL.
--------------------------------------------------------------------
"""
import os
import re

from locust import HttpUser, between, task

USER = os.environ.get("ROSHNI_LOAD_USER", "admin")
PASS = os.environ.get("ROSHNI_LOAD_PASS", "admin123")

_CSRF_RE = re.compile(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"')


class SchoolUser(HttpUser):
    """One simulated person: signs in once, then browses like real staff."""

    # Think-time between clicks — real users don't hammer the server.
    wait_time = between(1, 4)

    def on_start(self):
        """Sign in once when this virtual user starts."""
        resp = self.client.get("/login/")
        m = _CSRF_RE.search(resp.text)
        token = m.group(1) if m else ""
        self.client.post(
            "/login/",
            {
                "csrfmiddlewaretoken": token,
                "username": USER,
                "password": PASS,
            },
            headers={"Referer": self.client.base_url + "/login/"},
            name="/login/ (POST)",
        )

    # --- Browsing tasks. Higher number = happens more often. ---

    @task(5)
    def dashboard(self):
        self.client.get("/", name="/ dashboard")

    @task(3)
    def students(self):
        self.client.get("/students/", name="/students/")

    @task(2)
    def fee_collection(self):
        self.client.get("/fees/collection/", name="/fees/collection/")

    @task(2)
    def staff(self):
        self.client.get("/staff/", name="/staff/")

    @task(1)
    def timetable(self):
        self.client.get("/timetable/manage/", name="/timetable/manage/")

    @task(1)
    def reports(self):
        self.client.get("/reports/", name="/reports/")

    @task(1)
    def help_page(self):
        self.client.get("/help/", name="/help/")

    @task(2)
    def static_css(self):
        # The main stylesheet — served by WhiteNoise; a cheap, cacheable hit.
        self.client.get("/static/css/app.css", name="/static/css/app.css")
