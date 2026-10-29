"""The demo's settings, for the tests."""

import tempfile
from pathlib import Path

from example.settings import *  # noqa: F403
from example.settings import INSTALLED_APPS

# The tests' own models and admin site (resources of every kind).
INSTALLED_APPS = [*INSTALLED_APPS, "tests.calapp"]
ROOT_URLCONF = "tests.urls"

# A file, not in memory: the end-to-end tests' server answers from several
# threads, and an in-memory database is one connection they'd all share
# (closing it as the server stops, a request's thread would fail).
_DB = str(Path(tempfile.mkdtemp(prefix="django-ec-calendar-")) / "test.sqlite3")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _DB,
        "TEST": {"NAME": _DB},
    }
}
