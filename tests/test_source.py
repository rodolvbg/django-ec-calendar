"""CalendarSource: objects as events, and the dates a calendar sends back."""

import datetime
import zoneinfo

import pytest
from agenda.models import Booking, Holiday, Room
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.utils import timezone

from django_event_calendar import CalendarSource
from django_event_calendar.source import parse_moment

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")


class Bookings(CalendarSource):
    model = Booking
    calendar_start_field = "start"
    calendar_end_field = "end"
    calendar_color_field = "color"


class Holidays(CalendarSource):
    model = Holiday
    calendar_start_field = "first_day"
    calendar_end_field = "last_day"


class Titled(Bookings):
    calendar_title_field = "room"
    calendar_end_field = None
    calendar_color_field = None


def at(day, hour):
    return datetime.datetime(2026, 10, day, hour, tzinfo=MADRID)


def request(**query):
    return RequestFactory().get("/", query)


@pytest.fixture
def room(db):
    return Room.objects.create(name="Blue", color="#00f")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-29", datetime.date(2026, 10, 29)),
        ("2026-10-29T10:30:00", datetime.datetime(2026, 10, 29, 10, 30)),
        ("2026-10-29T10:30", datetime.datetime(2026, 10, 29, 10, 30)),
        ("", None),
        (None, None),
        ("tomorrow", None),
        ("2026-13-45", None),
    ],
)
def test_parse_moment(value, expected):
    assert parse_moment(value) == expected


def test_an_event_at_a_time_in_the_current_time_zone(room):
    booking = Booking.objects.create(
        title="Call", room=room, start=at(29, 10), end=at(29, 11)
    )
    assert Bookings().get_calendar_event(request(), booking) == {
        "id": str(booking.pk),
        "title": "Call",
        # Madrid's wall-clock time, without an offset.
        "start": "2026-10-29T10:00:00",
        "end": "2026-10-29T11:00:00",
        "allDay": False,
        "color": "#00f",
    }
    with timezone.override("UTC"):
        event = Bookings().get_calendar_event(request(), booking)
    assert event["start"] == "2026-10-29T09:00:00"


def test_an_all_day_event_ends_the_day_after(db):
    holiday = Holiday.objects.create(
        name="Retreat",
        first_day=datetime.date(2026, 11, 2),
        last_day=datetime.date(2026, 11, 4),
    )
    event = Holidays().get_calendar_event(request(), holiday)
    assert event["allDay"] is True
    assert (event["start"], event["end"]) == ("2026-11-02", "2026-11-05")
    # One day, without a last: that day.
    holiday.last_day = None
    event = Holidays().get_calendar_event(request(), holiday)
    assert event["end"] == "2026-11-03"


def test_its_title_and_no_end(room):
    booking = Booking.objects.create(
        title="Call", room=room, start=at(29, 10), end=at(29, 11)
    )
    event = Titled().get_calendar_event(request(), booking)
    assert event["title"] == "Blue"
    assert "end" not in event
    assert "color" not in event


def test_all_day_by_a_field(room):
    class Flagged(Bookings):
        calendar_all_day_field = "title"  # Any value: true when it's set.

    booking = Booking.objects.create(
        title="x", room=room, start=at(29, 10), end=at(29, 11)
    )
    assert Flagged().get_calendar_event(request(), booking)["allDay"] is True


def test_a_naive_datetime_as_it_is():
    assert Bookings().format_moment(datetime.datetime(2026, 1, 2, 3, 4)) == (
        "2026-01-02T03:04:00"
    )
    assert Bookings().format_moment(None) is None


def test_the_events_of_a_range(room):
    def book(title, start, end):
        Booking.objects.create(title=title, room=room, start=start, end=end)

    book("Before", at(20, 10), at(20, 11))
    book("Across the start", at(25, 23), at(26, 1))
    book("Inside", at(27, 10), at(27, 11))
    book("Across the end", at(31, 23), datetime.datetime(2026, 11, 1, 2, tzinfo=MADRID))
    book("After", datetime.datetime(2026, 11, 2, 10, tzinfo=MADRID), at(31, 11))
    events = Bookings().get_calendar_events(
        request(start="2026-10-26T00:00:00", end="2026-11-02T00:00:00"),
        Booking.objects.order_by("start"),
    )
    assert [event["title"] for event in events] == [
        "Across the start",
        "Inside",
        "Across the end",
    ]
    # No range: all of them.
    assert len(Bookings().get_calendar_events(request(), Booking.objects.all())) == 5


def test_the_days_of_a_range(db):
    Holiday.objects.create(
        name="Long",
        first_day=datetime.date(2026, 10, 20),
        last_day=datetime.date(2026, 10, 27),
    )
    Holiday.objects.create(name="One day", first_day=datetime.date(2026, 10, 29))
    Holiday.objects.create(name="Before", first_day=datetime.date(2026, 10, 1))
    events = Holidays().get_calendar_events(
        request(start="2026-10-26", end="2026-11-02"), Holiday.objects.order_by("pk")
    )
    assert [event["title"] for event in events] == ["Long", "One day"]


def test_an_event_without_an_end_in_a_range(room):
    Booking.objects.create(title="In", room=room, start=at(27, 10), end=at(27, 11))
    Booking.objects.create(title="Out", room=room, start=at(20, 10), end=at(27, 11))
    events = Titled().get_calendar_events(
        request(start="2026-10-26T00:00:00"), Booking.objects.order_by("pk")
    )
    # Without an end field, only its start says it's there.
    assert [event["id"] for event in events] == [
        str(Booking.objects.get(title="In").pk)
    ]


def test_moved_values_at_a_time():
    assert Bookings().moved_values("2026-10-29T10:00:00", "2026-10-29T12:30:00") == {
        "start": at(29, 10),
        "end": datetime.datetime(2026, 10, 29, 12, 30, tzinfo=MADRID),
    }
    # A day (an all-day drop): its midnight.
    assert Bookings().moved_values("2026-10-29", "")["start"] == at(29, 0)
    assert Bookings().moved_values("2026-10-29T10:00:00", None)["end"] is None
    assert Titled().moved_values("2026-10-29T10:00:00", "x") is None
    assert Titled().moved_values("2026-10-29T10:00:00", "") == {"start": at(29, 10)}


def test_moved_values_of_days():
    assert Holidays().moved_values("2026-11-02", "2026-11-05") == {
        "first_day": datetime.date(2026, 11, 2),
        "last_day": datetime.date(2026, 11, 4),
    }
    # From a time view: its days.
    assert Holidays().moved_values("2026-11-02T10:00:00", "2026-11-03T00:00:00") == {
        "first_day": datetime.date(2026, 11, 2),
        "last_day": datetime.date(2026, 11, 2),
    }


@pytest.mark.parametrize("value", [None, "", "never"])
def test_moved_values_without_a_start(value):
    assert Bookings().moved_values(value, "2026-10-29T10:00:00") is None


def test_without_time_zones(room, settings):
    settings.USE_TZ = False
    assert Bookings().moved_values("2026-10-29T10:00:00", "")["start"] == (
        datetime.datetime(2026, 10, 29, 10)
    )


def test_misconfigured():
    class NoStart(CalendarSource):
        model = Booking

    class Unknown(CalendarSource):
        model = Booking
        calendar_start_field = "when"

    with pytest.raises(ImproperlyConfigured, match="calendar_start_field is needed"):
        NoStart().dates_only  # noqa: B018
    with pytest.raises(ImproperlyConfigured, match="'when' isn't a field"):
        Unknown().dates_only  # noqa: B018
