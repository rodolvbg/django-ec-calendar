"""EventFeedView and {% ec_calendar %}: a calendar on your own pages."""

import datetime
import json
import re
import zoneinfo

import pytest
from agenda.models import Booking, Room
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse

from django_ec_calendar import EventFeedView

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")


@pytest.fixture
def call(db):
    room = Room.objects.create(name="Blue", color="#00f")
    return Booking.objects.create(
        title="Call",
        room=room,
        start=datetime.datetime(2026, 10, 27, 10, tzinfo=MADRID),
        end=datetime.datetime(2026, 10, 27, 11, tzinfo=MADRID),
    )


def test_the_feed_leads_to_their_pages(client, call):
    events = client.get(
        reverse("booking-events"),
        {"start": "2026-10-26T00:00:00", "end": "2026-11-02T00:00:00"},
    ).json()
    assert events == [
        {
            "id": str(call.pk),
            "title": "Call",
            "start": "2026-10-27T10:00:00",
            "end": "2026-10-27T11:00:00",
            "allDay": False,
            "color": "#00f",
            "extendedProps": {"url": reverse("booking", args=[call.pk])},
        }
    ]
    assert client.get(reverse("booking-events"), {"start": "2026-11-02"}).json() == []


def test_without_get_absolute_url(call):
    class Rooms(EventFeedView):
        model = Room
        calendar_start_field = "name"

    assert Rooms().get_calendar_event_url(call.room) is None
    assert Rooms().get_source_model() is Room

    class Nowhere(EventFeedView):
        model = Booking
        calendar_start_field = "start"

        def get_calendar_event_url(self, obj):
            return None

    event = Nowhere().get_calendar_event(RequestFactory().get("/"), call)
    assert "extendedProps" not in event


def test_the_page(client, call):
    html = client.get(reverse("calendar")).content.decode()
    assert "event-calendar.min.css" in html
    assert "django_ec_calendar/calendar.js" in html
    element = re.search(r'data-django-ec-calendar="([^"]+)"', html).group(1)
    data = json.loads(
        re.search(
            rf'<script id="{element}" type="application/json">(.*?)</script>', html
        ).group(1)
    )
    assert data["events"] == reverse("booking-events")
    assert data["view"] == "timeGridWeek"
    assert data["views"] == ["dayGridMonth", "timeGridWeek", "listWeek"]
    assert data["options"] == {"slotMinTime": "07:00"}
    # Read-only: nothing to add, move, or send.
    assert (data["add"], data["move"], data["csrfToken"]) == (None, None, "")


def test_its_own_id_and_no_views():
    template = Template(
        '{% load ec_calendar %}{% ec_calendar "/events/" id="mine" views="" %}'
    )
    html = template.render(Context({"request": RequestFactory().get("/")}))
    assert 'id="mine"' in html
    data = json.loads(
        re.search(
            r'<script id="mine-config" type="application/json">(.*?)</script>', html
        ).group(1)
    )
    assert data["views"] == []
    assert data["view"] == "dayGridMonth"


def test_the_sites_time_zone(settings):
    from django.utils import timezone

    from django_ec_calendar.config import site_time_zone

    with timezone.override("Asia/Kolkata"):
        assert site_time_zone() == "+05:30"
    settings.USE_TZ = False
    assert site_time_zone() == "local"
