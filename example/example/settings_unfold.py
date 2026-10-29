"""The demo with django-unfold: ``DJANGO_SETTINGS_MODULE=example.settings_unfold``."""

from .settings import *  # noqa: F403
from .settings import INSTALLED_APPS

INSTALLED_APPS = ["unfold", *INSTALLED_APPS]

ROOT_URLCONF = "example.urls_unfold"

from django_ec_calendar.unfold import calendar_navigation  # noqa: E402

UNFOLD = {
    "SIDEBAR": {
        "show_all_applications": True,
        "navigation": [
            {
                "title": "Agenda",
                "items": [
                    # Each list, and its calendar: active on its own page.
                    *calendar_navigation(
                        "agenda.Booking", calendar_title="Bookings' calendar"
                    ),
                    *calendar_navigation(
                        "agenda.Appointment", calendar_title="Appointments' calendar"
                    ),
                ],
            },
        ],
    },
}
