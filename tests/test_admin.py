"""CalendarAdminMixin: the changelist's calendar, its events and moves."""

import datetime
import json
import re
import zoneinfo

import pytest
from agenda.admin import BookingAdmin
from agenda.models import Booking, Holiday, Room
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse
from django.utils import translation

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
BOOKINGS = "/admin/agenda/booking/"
EVENTS = f"{BOOKINGS}calendar/events/"
MOVE = f"{BOOKINGS}calendar/move/"
WEEK = {"start": "2026-10-26T00:00:00", "end": "2026-11-02T00:00:00"}


def at(day, hour, minute=0):
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=MADRID)


def config(html, element="django-event-calendar-config"):
    match = re.search(
        rf'<script id="{element}" type="application/json">(.*?)</script>', html
    )
    return json.loads(match.group(1)) if match else None


@pytest.fixture
def blue(db):
    return Room.objects.create(name="Blue", color="#00f")


@pytest.fixture
def green(db):
    return Room.objects.create(name="Green", color="#0a0")


@pytest.fixture
def call(blue):
    return Booking.objects.create(
        title="Call", room=blue, start=at(27, 10), end=at(27, 11)
    )


@pytest.fixture
def superuser(admin_client):
    return admin_client


def staff(*codenames):
    user = User.objects.create_user("clerk", password="pw", is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    client = Client()
    client.force_login(user)
    return client


class TestChangelist:
    def test_links_to_the_calendar_with_its_filters(self, superuser, blue):
        html = superuser.get(BOOKINGS).content.decode()
        assert f'href="{BOOKINGS}calendar/"' in html
        html = superuser.get(BOOKINGS, {"room__id__exact": blue.pk}).content.decode()
        assert f'href="{BOOKINGS}calendar/?room__id__exact={blue.pk}"' in html

    def test_not_in_a_popup(self, superuser):
        html = superuser.get(BOOKINGS, {"_popup": "1"}).content.decode()
        assert "calendar/" not in html

    def test_a_redirect_passes_as_it_is(self, superuser):
        assert superuser.get(BOOKINGS, {"nothing": "1"}).status_code == 302

    def test_off_without_its_start_field(self, rf, superuser):
        class Plain(BookingAdmin):
            calendar_start_field = ""

        model_admin = Plain(Booking, admin.site)
        assert not model_admin.uses_calendar
        names = [getattr(url, "name", "") for url in model_admin.get_urls()]
        assert "agenda_booking_calendar" not in names
        request = rf.get(BOOKINGS)
        request.user = User.objects.get(username="admin")
        response = model_admin.changelist_view(request)
        assert response.template_name != model_admin.calendar_change_list_template


class TestCalendarPage:
    def test_its_configuration(self, superuser):
        response = superuser.get(f"{BOOKINGS}calendar/")
        html = response.content.decode()
        data = config(html)
        assert data["events"] == EVENTS
        assert data["params"] == {}
        assert data["view"] == "timeGridWeek"
        assert data["views"] == [
            "dayGridMonth",
            "timeGridWeek",
            "timeGridDay",
            "listMonth",
        ]
        assert data["add"] == reverse("admin:agenda_booking_add")
        assert data["move"] == MOVE
        assert data["csrfToken"]
        assert data["datesOnly"] is False
        assert data["options"] == {"slotMinTime": "07:00", "slotMaxTime": "21:00"}
        assert data["texts"]["today"] == "Today"
        assert data["locale"] == "en-us"
        assert data["firstDay"] == 0
        assert "Calendar of bookings" in html
        assert "event-calendar.min.js" in html
        assert "django_event_calendar/calendar.js" in html
        assert f'href="{reverse("admin:agenda_booking_add")}"' in html

    def test_keeps_the_changelists_filters(self, superuser, blue):
        query = {"room__id__exact": str(blue.pk), "q": "call"}
        html = superuser.get(f"{BOOKINGS}calendar/", query).content.decode()
        assert config(html)["params"] == query
        assert f'href="{BOOKINGS}?room__id__exact={blue.pk}&amp;q=call"' in html

    def test_in_spanish(self, superuser):
        with translation.override("es"):
            html = superuser.get(f"{BOOKINGS}calendar/").content.decode()
        data = config(html)
        assert data["locale"] == "es"
        assert data["firstDay"] == 1
        assert data["texts"]["today"] == "Hoy"
        assert "Calendario de bookings" in html

    def test_who_may_only_view(self, blue):
        client = staff("view_booking")
        html = client.get(f"{BOOKINGS}calendar/").content.decode()
        data = config(html)
        assert data["add"] is None
        assert data["csrfToken"] == ""  # Nothing to send.
        assert reverse("admin:agenda_booking_add") not in html

    def test_who_may_not_view(self, db):
        assert staff().get(f"{BOOKINGS}calendar/").status_code == 403

    def test_without_moves_or_adding(self, superuser, rf):
        class ReadOnly(BookingAdmin):
            calendar_editable = False
            calendar_selectable = False

        request = rf.get("/")
        request.user = User.objects.get(username="admin")
        data = ReadOnly(Booking, admin.site).get_calendar_config(request)
        assert (data["add"], data["move"]) == (None, None)

    def test_of_days(self, superuser):
        html = superuser.get("/admin/agenda/holiday/calendar/").content.decode()
        assert config(html)["datesOnly"] is True

    @pytest.mark.parametrize(
        ("django", "markup"), [((6, 0), "<ol"), ((5, 2), "&rsaquo;")]
    )
    def test_breadcrumbs_as_the_admins(self, superuser, monkeypatch, django, markup):
        monkeypatch.setattr("django.VERSION", django)
        html = superuser.get(f"{BOOKINGS}calendar/").content.decode()
        assert markup in html.split('id="content-main"')[0]


class TestEvents:
    def test_of_the_range_with_where_they_lead(self, superuser, call, green):
        Booking.objects.create(
            title="Later", room=green, start=at(5, 10), end=at(5, 11)
        )
        events = superuser.get(EVENTS, WEEK).json()
        assert events == [
            {
                "id": str(call.pk),
                "title": "Call",
                "start": "2026-10-27T10:00:00",
                "end": "2026-10-27T11:00:00",
                "allDay": False,
                "color": "#00f",
                "extendedProps": {
                    "url": reverse("admin:agenda_booking_change", args=[call.pk])
                },
                "editable": True,
            }
        ]

    def test_of_the_changelists_filters_and_search(self, superuser, call, green):
        Booking.objects.create(
            title="Green call", room=green, start=at(28, 9), end=at(28, 10)
        )
        Booking.objects.create(
            title="Talk", room=green, start=at(28, 11), end=at(28, 12)
        )

        def titles(**query):
            events = superuser.get(EVENTS, {**WEEK, **query}).json()
            return [event["title"] for event in events]

        assert sorted(titles(room__id__exact=green.pk)) == ["Green call", "Talk"]
        assert sorted(titles(q="call")) == ["Call", "Green call"]
        assert sorted(titles()) == ["Call", "Green call", "Talk"]

    def test_an_unknown_filter(self, superuser):
        response = superuser.get(EVENTS, {**WEEK, "nothing": "1"})
        assert response.status_code == 400
        assert response.json() == {"error": "Unknown filter."}

    def test_for_who_may_only_view(self, call):
        [event] = staff("view_booking").get(EVENTS, WEEK).json()
        assert event["editable"] is False
        assert event["extendedProps"]["url"]

    def test_who_may_not_view(self, call):
        assert staff().get(EVENTS, WEEK).status_code == 403

    def test_without_an_end_nor_a_change_page(self, superuser, call, rf):
        class Starts(BookingAdmin):
            calendar_end_field = None

        request = rf.get("/")
        request.user = User.objects.get(username="admin")
        site = admin.AdminSite(name="elsewhere")  # Not registered: no URLs.
        event = Starts(Booking, site).get_calendar_event(request, call)
        assert event["durationEditable"] is False
        assert "extendedProps" not in event
        assert "end" not in event

    def test_days(self, superuser):
        Holiday.objects.create(
            name="Retreat",
            first_day=datetime.date(2026, 10, 28),
            last_day=datetime.date(2026, 10, 29),
        )
        [event] = superuser.get(
            "/admin/agenda/holiday/calendar/events/",
            {"start": "2026-10-26", "end": "2026-11-02"},
        ).json()
        assert (event["start"], event["end"], event["allDay"]) == (
            "2026-10-28",
            "2026-10-30",
            True,
        )


class TestMove:
    def test_saves_and_logs_it(self, superuser, call):
        response = superuser.post(
            MOVE,
            {
                "pk": call.pk,
                "start": "2026-10-28T15:00:00",
                "end": "2026-10-28T16:30:00",
            },
        )
        assert response.status_code == 200
        assert response.json()["event"]["start"] == "2026-10-28T15:00:00"
        call.refresh_from_db()
        assert (call.start, call.end) == (at(28, 15), at(28, 16, 30))
        entry = LogEntry.objects.get()
        assert json.loads(entry.change_message) == [
            {"changed": {"fields": ["start", "end"]}}
        ]

    def test_checked_by_the_model(self, superuser, call):
        response = superuser.post(
            MOVE,
            {
                "pk": call.pk,
                "start": "2026-10-28T15:00:00",
                "end": "2026-10-28T14:00:00",
            },
        )
        assert response.status_code == 400
        assert response.json() == {"error": "It can't end before it starts."}
        call.refresh_from_db()
        assert call.start == at(27, 10)

    def test_not_dates(self, superuser, call):
        response = superuser.post(MOVE, {"pk": call.pk, "start": "soon", "end": ""})
        assert response.status_code == 400

    @pytest.mark.parametrize("pk", ["999", "x", ""])
    def test_what_isnt_there(self, superuser, call, pk):
        response = superuser.post(MOVE, {"pk": pk, "start": "2026-10-28T15:00:00"})
        assert response.status_code == 404

    def test_only_for_who_may_change_it(self, call):
        client = staff("view_booking")
        response = client.post(MOVE, {"pk": call.pk, "start": "2026-10-28T15:00:00"})
        assert response.status_code == 403

    def test_only_posted(self, superuser):
        assert superuser.get(MOVE).status_code == 405

    def test_days(self, superuser):
        holiday = Holiday.objects.create(
            name="Retreat", first_day=datetime.date(2026, 10, 28)
        )
        superuser.post(
            "/admin/agenda/holiday/calendar/move/",
            {"pk": holiday.pk, "start": "2026-11-02", "end": "2026-11-05"},
        )
        holiday.refresh_from_db()
        assert (holiday.first_day, holiday.last_day) == (
            datetime.date(2026, 11, 2),
            datetime.date(2026, 11, 4),
        )


class TestAddFromTheCalendar:
    def test_the_add_page_with_the_dates(self, superuser):
        response = superuser.get(
            reverse("admin:agenda_booking_add"),
            {"start": "2026-10-28T09:30:00", "end": "2026-10-28T11:00:00"},
        )
        initial = response.context["adminform"].form.initial
        assert (initial["start"], initial["end"]) == (at(28, 9, 30), at(28, 11))

    def test_of_days(self, superuser):
        response = superuser.get(
            reverse("admin:agenda_holiday_add"),
            {"start": "2026-10-28", "end": "2026-10-30"},
        )
        initial = response.context["adminform"].form.initial
        assert (initial["first_day"], initial["last_day"]) == (
            datetime.date(2026, 10, 28),
            datetime.date(2026, 10, 29),
        )

    def test_not_from_the_calendar(self, superuser):
        response = superuser.get(reverse("admin:agenda_booking_add"))
        assert "start" not in response.context["adminform"].form.initial

    def test_one_click_a_start_only(self, superuser):
        response = superuser.get(
            reverse("admin:agenda_booking_add"), {"start": "2026-10-28T09:30:00"}
        )
        initial = response.context["adminform"].form.initial
        assert initial["start"] == at(28, 9, 30)
        assert "end" not in initial

    def test_not_dates_not_in_the_fields(self, superuser):
        response = superuser.get(reverse("admin:agenda_booking_add"), {"start": "soon"})
        assert "start" not in response.context["adminform"].form.initial
