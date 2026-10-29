"""Business hours and closed times; the options and permissions of each
request."""

import datetime
import json
import re
import zoneinfo

import pytest
from agenda.admin import AppointmentAdmin, BookingAdmin, HolidayAdmin
from agenda.models import Appointment, Booking, Holiday, Professional, Room
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory

from django_ec_calendar import CalendarSource
from django_ec_calendar.source import CLOSED, NO_RESOURCE

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
APPOINTMENTS = "/admin/agenda/appointment/"
THURSDAY = datetime.date(2026, 10, 29)
FRIDAY = THURSDAY + datetime.timedelta(days=1)
WEEKDAYS = [1, 2, 3, 4, 5]


def at(hour, minute=0, day=29):
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=MADRID)


def wall(hour, minute=0, day=29):
    return datetime.datetime(2026, 10, day, hour, minute)


def request():
    return RequestFactory().get("/")


def config(html):
    match = re.search(
        r'<script id="django-ec-calendar-config" type="application/json">'
        r"(.*?)</script>",
        html,
    )
    return json.loads(match.group(1))


class Shop(CalendarSource):
    model = Booking
    calendar_start_field = "start"
    calendar_end_field = "end"
    calendar_business_hours = [
        {"days": WEEKDAYS, "start": "09:00", "end": "14:00"},
        {"days": WEEKDAYS, "start": "13:00", "end": "20:00"},  # Overlapping.
        {"days": [6], "start": "10:00", "end": "24:00"},
    ]


class TestClosedRanges:
    def test_out_of_its_hours(self):
        ranges = Shop().get_calendar_closed_ranges(request(), THURSDAY, FRIDAY)
        assert ranges == [
            (wall(0), wall(9), False),
            (wall(20), wall(0, day=30), False),
        ]

    def test_a_day_closed_and_one_open_until_midnight(self):
        friday, saturday, sunday = (
            THURSDAY + datetime.timedelta(days=n) for n in (1, 2, 3)
        )
        ranges = Shop().get_calendar_closed_ranges(
            request(),
            datetime.datetime.combine(saturday, datetime.time(12)),
            datetime.datetime.combine(sunday, datetime.time(1)),
        )
        assert ranges == [
            (wall(0, day=31), wall(10, day=31), False),
            # Sunday: no hours.
            (
                datetime.datetime(2026, 11, 1),
                datetime.datetime(2026, 11, 2),
                False,
            ),
        ]
        assert friday.weekday() == 4

    def test_every_day_without_days(self):
        class Always(Shop):
            calendar_business_hours = [{"start": "08:00", "end": "18:00"}]

        sunday = datetime.date(2026, 11, 1)
        monday = sunday + datetime.timedelta(days=1)
        assert Always().get_calendar_closed_ranges(request(), sunday, monday) == [
            (datetime.datetime(2026, 11, 1), datetime.datetime(2026, 11, 1, 8), False),
            (
                datetime.datetime(2026, 11, 1, 18),
                datetime.datetime(2026, 11, 2),
                False,
            ),
        ]

    def test_none_without_hours(self):
        class Open(Shop):
            calendar_business_hours = None

        assert Open().get_calendar_closed_ranges(request(), THURSDAY, FRIDAY) == []

    def test_its_closed_times_too(self):
        class Holidays(Shop):
            calendar_business_hours = None

            def get_calendar_closed(self, request, start, end, resource=None):
                assert (start, end) == (THURSDAY, THURSDAY + datetime.timedelta(1))
                return [
                    (THURSDAY, THURSDAY + datetime.timedelta(1)),
                    (at(15), at(16)),
                ]

        ranges = Holidays().get_calendar_closed_ranges(request(), at(8), at(9))
        assert ranges == [
            (wall(0), wall(0, day=30), True),
            (wall(15), wall(16), False),
        ]

    def test_days_have_no_hours(self, db):
        class Days(CalendarSource):
            model = Holiday
            calendar_start_field = "first_day"
            calendar_business_hours = Shop.calendar_business_hours

        assert Days().get_calendar_closed_ranges(request(), THURSDAY, FRIDAY) == []
        assert Days().get_calendar_hours_options(request()) == {}

    def test_not_a_time(self):
        class Wrong(Shop):
            calendar_business_hours = [{"start": "nine", "end": "14:00"}]

        with pytest.raises(ImproperlyConfigured, match="'nine' isn't a time"):
            Wrong().get_calendar_closed_ranges(request(), THURSDAY, FRIDAY)


class TestOpen:
    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            (at(10), at(11), True),
            (at(13), at(19), True),  # Across the overlapping hours.
            (at(8), at(10), False),
            (at(19), at(21), False),
            (at(10), None, True),
            (at(8), None, False),
            (at(9), at(9), True),  # No length: its start.
        ],
    )
    def test_in_its_hours(self, start, end, expected):
        assert Shop().is_calendar_open(request(), start, end) is expected


class TestClosedEvents:
    def test_as_background_events_and_a_whole_day_twice(self, db):
        class Holidays(Shop):
            def get_calendar_closed(self, request, start, end, resource=None):
                return [(THURSDAY, THURSDAY + datetime.timedelta(1))]

        events = Holidays().get_calendar_closed_events(request(), at(0), at(0, day=30))
        assert events[0] == {
            "start": "2026-10-29T00:00:00",
            "end": "2026-10-29T09:00:00",
            "allDay": False,
            "display": "background",
            "classNames": [CLOSED],
            "extendedProps": {"closed": True},
        }
        # The holiday: in the time views, and in the month views.
        whole_day = [
            (event["start"], event["end"], event["allDay"])
            for event in events
            if event["start"] in ("2026-10-29", "2026-10-29T00:00:00")
            and event["end"] in ("2026-10-30", "2026-10-30T00:00:00")
        ]
        assert whole_day == [
            ("2026-10-29T00:00:00", "2026-10-30T00:00:00", False),
            ("2026-10-29", "2026-10-30", True),
        ]

    def test_each_resources_in_its_column(self, db):
        blue = Room.objects.create(name="Blue")

        class ByRoom(Shop):
            calendar_resource_field = "room"

            def get_calendar_business_hours(self, request, resource=None):
                if resource == str(blue.pk):
                    return [{"start": "00:00", "end": "24:00"}]  # Always open.
                return super().get_calendar_business_hours(request, resource)

        events = ByRoom().get_calendar_closed_events(request(), at(0), at(0, day=30))
        assert {tuple(e.get("resourceIds", ())) for e in events} == {()}

    def test_in_the_feed_only_with_a_range(self, admin_client):
        events = admin_client.get(f"{APPOINTMENTS}calendar/events/").json()
        assert events == []
        events = admin_client.get(
            f"{APPOINTMENTS}calendar/events/",
            {"start": "2026-10-29T00:00:00", "end": "2026-10-30T00:00:00"},
        ).json()
        resources = {tuple(e.get("resourceIds", ())) for e in events}
        assert () in resources and (NO_RESOURCE,) in resources


class TestFitted:
    def test_to_its_first_and_last_times_and_days(self):
        assert Shop().get_calendar_hours_options(request()) == {
            "slotMinTime": "09:00:00",
            "slotMaxTime": "24:00:00",
            "hiddenDays": [0],
        }

    def test_not_when_off_or_without_hours(self):
        class Unfitted(Shop):
            calendar_fit_hours = False

        class Open(Shop):
            calendar_business_hours = None

        class Always(Shop):
            calendar_business_hours = [{"start": "07:30", "end": "19:00"}]

        assert Unfitted().get_calendar_hours_options(request()) == {}
        assert Open().get_calendar_hours_options(request()) == {}
        assert Always().get_calendar_hours_options(request()) == {
            "slotMinTime": "07:30:00",
            "slotMaxTime": "19:00:00",
        }

    def test_in_the_admins_configuration_under_its_own_options(
        self, admin_client, monkeypatch
    ):
        data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
        assert data["options"] == {
            "slotMinTime": "09:00:00",
            "slotMaxTime": "20:00:00",
            "hiddenDays": [0, 6],
        }
        assert data["outsideHours"] == "block"
        model_admin = admin.site._registry[Appointment]
        monkeypatch.setattr(model_admin, "calendar_options", {"hiddenDays": []})
        data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
        assert data["options"]["hiddenDays"] == []


class TestMovesInItsHours:
    @pytest.fixture
    def ana(self, db):
        return Professional.objects.create(name="Ana")  # 9 to 14.

    @pytest.fixture
    def maria(self, ana):
        return Appointment.objects.create(
            client="María", professional=ana, start=at(9), minutes=60
        )

    def move(self, client, maria, start, **extra):
        return client.post(
            f"{APPOINTMENTS}calendar/move/",
            {"pk": maria.pk, "start": start, "end": "", **extra},
        )

    def test_in_them(self, admin_client, maria):
        assert self.move(admin_client, maria, "2026-10-29T12:00:00").status_code == 200

    def test_not_out_of_them(self, admin_client, maria):
        response = self.move(admin_client, maria, "2026-10-29T15:00:00")
        assert response.status_code == 400
        assert response.json() == {"error": "It's out of the business hours."}
        maria.refresh_from_db()
        assert maria.start == at(9)

    def test_nor_out_of_those_of_where_it_goes(self, admin_client, maria):
        luis = Professional.objects.create(name="Luis")  # 16 to 20.
        response = self.move(
            admin_client, maria, "2026-10-29T10:00:00", resource=str(luis.pk)
        )
        assert response.status_code == 400

    def test_shaded_only(self, admin_client, maria, monkeypatch):
        model_admin = admin.site._registry[Appointment]
        monkeypatch.setattr(model_admin, "calendar_outside_hours", "shade")
        assert self.move(admin_client, maria, "2026-10-29T15:00:00").status_code == 200

    def test_without_resources(self, db):
        class Shut(BookingAdmin):
            calendar_editable = True
            calendar_confirm_move = False
            calendar_outside_hours = "block"
            calendar_business_hours = [{"start": "09:00", "end": "10:00"}]

        room = Room.objects.create(name="Blue")
        booking = Booking.objects.create(title="x", room=room, start=at(9), end=at(10))
        model_admin = Shut(Booking, admin.site)
        assert model_admin._open_for(request(), booking, None) is True
        booking.start, booking.end = at(11), at(12)
        assert model_admin._open_for(request(), booking, None) is False

    def test_days(self, db):
        class ClosedDays(HolidayAdmin):
            calendar_outside_hours = "block"

            def get_calendar_closed(self, request, start, end, resource=None):
                return [(THURSDAY, THURSDAY + datetime.timedelta(1))]

        holiday = Holiday(name="x", first_day=THURSDAY)
        model_admin = ClosedDays(Holiday, admin.site)
        assert model_admin._open_for(request(), holiday, None) is False
        holiday.first_day = THURSDAY + datetime.timedelta(1)
        assert model_admin._open_for(request(), holiday, None) is True


class TestEachRequest:
    """Each option has its method, taking the request."""

    @pytest.fixture
    def model_admin(self):
        return admin.site._registry[Appointment]

    def test_the_views_and_details(self, admin_client, model_admin, monkeypatch):
        monkeypatch.setattr(model_admin, "get_calendar_view", lambda r: "listWeek")
        monkeypatch.setattr(model_admin, "get_calendar_views", lambda r: ["listWeek"])
        monkeypatch.setattr(model_admin, "get_calendar_detail_fields", lambda r: ())
        monkeypatch.setattr(model_admin, "get_calendar_url_state", lambda r: False)
        monkeypatch.setattr(
            model_admin, "get_calendar_highlight_today", lambda r: False
        )
        monkeypatch.setattr(model_admin, "get_calendar_confirm_move", lambda r: False)
        monkeypatch.setattr(model_admin, "get_calendar_filters", lambda r: False)
        html = admin_client.get(f"{APPOINTMENTS}calendar/").content.decode()
        data = config(html)
        assert (data["view"], data["views"]) == ("listWeek", ["listWeek"])
        assert (data["urlState"], data["highlightToday"], data["confirmMove"]) == (
            False,
            False,
            False,
        )
        assert 'id="changelist-filter"' not in html
        Appointment.objects.create(client="María", start=at(9), minutes=30)
        [event] = [
            e
            for e in admin_client.get(
                f"{APPOINTMENTS}calendar/events/",
                {"start": "2026-10-29T00:00:00", "end": "2026-10-30T00:00:00"},
            ).json()
            if e.get("title")
        ]
        assert "details" not in event.get("extendedProps", {})

    def test_who_may_move_each(self, admin_client, model_admin, monkeypatch, db):
        ana = Professional.objects.create(name="Ana")
        mine = Appointment.objects.create(
            client="Mine", professional=ana, start=at(9), minutes=30
        )
        other = Appointment.objects.create(client="Other", start=at(10), minutes=30)
        monkeypatch.setattr(
            model_admin,
            "has_calendar_move_permission",
            lambda request, obj=None: obj is None or obj.professional_id == ana.pk,
        )
        events = {
            e["title"]: e
            for e in admin_client.get(
                f"{APPOINTMENTS}calendar/events/",
                {"start": "2026-10-29T00:00:00", "end": "2026-10-30T00:00:00"},
            ).json()
            if e.get("title")
        }
        assert (events["Mine"]["editable"], events["Other"]["editable"]) == (
            True,
            False,
        )
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {"pk": other.pk, "start": "2026-10-29T11:00:00"},
        )
        assert response.status_code == 403
        assert mine.pk

    def test_who_may_add_from_it(self, admin_client, model_admin, monkeypatch):
        monkeypatch.setattr(model_admin, "has_calendar_add_permission", lambda r: False)
        data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
        assert data["add"] is None

    def test_whether_its_resource_may_change(
        self, admin_client, model_admin, monkeypatch
    ):
        monkeypatch.setattr(
            model_admin, "get_calendar_resource_editable", lambda r: False
        )
        data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
        assert data["resource"]["editable"] is False

    def test_its_label_of_none(self, db):
        class Named(AppointmentAdmin):
            def get_calendar_resource_empty_label(self, request):
                return f"Nobody ({request.GET['who']})"

        rf = RequestFactory().get("/", {"who": "yet"})
        resources = Named(Appointment, admin.site).get_calendar_resources(rf)
        assert resources[-1]["title"] == "Nobody (yet)"
