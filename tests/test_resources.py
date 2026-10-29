"""Resources (a foreign key, many-to-many, choices), durations, details, the
calendar's own queryset, and back to the calendar after a save."""

import datetime
import json
import re
import zoneinfo

import pytest
from agenda.admin import AppointmentAdmin
from agenda.models import Appointment, Professional
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.urls import reverse

from django_ec_calendar import CalendarSource
from django_ec_calendar.source import NO_RESOURCE, display_value
from tests.calapp.admin import ByAttendees
from tests.calapp.admin import site as calendars
from tests.calapp.models import Meeting, Person

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
APPOINTMENTS = "/admin/agenda/appointment/"
MEETINGS = "/calendars/calapp/meeting/"
DAY = {"start": "2026-10-29T00:00:00", "end": "2026-10-30T00:00:00"}


def at(hour, minute=0, day=29):
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=MADRID)


def booked(events):
    """The events but the closed times (background ones)."""
    return [event for event in events if event.get("display") != "background"]


def config(html):
    match = re.search(
        r'<script id="django-ec-calendar-config" type="application/json">'
        r"(.*?)</script>",
        html,
    )
    return json.loads(match.group(1))


@pytest.fixture
def ana(db):
    return Professional.objects.create(name="Ana")


@pytest.fixture
def luis(db):
    return Professional.objects.create(name="Luis")


@pytest.fixture
def maria(ana):
    return Appointment.objects.create(
        client="María", professional=ana, start=at(9), minutes=45
    )


class TestForeignKey:
    def test_its_resources_as_it_limits_them_and_one_for_none(
        self, admin_client, ana, luis
    ):
        Professional.objects.create(name="Retired", active=False)
        data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
        assert data["resources"] == [
            {"id": str(ana.pk), "title": "Ana"},
            {"id": str(luis.pk), "title": "Luis"},
            {"id": NO_RESOURCE, "title": "No professional"},
        ]
        assert data["resource"] == {
            "param": "professional",
            "empty": NO_RESOURCE,
            "editable": True,
            "message": "It can't be moved to another professional.",
        }

    @pytest.mark.parametrize(
        ("query", "titles"),
        [
            ({"professional__id__exact": "{ana}"}, ["Ana"]),
            ({"professional__exact": "{luis}"}, ["Luis"]),
            ({"professional__in": "{ana},{luis}"}, ["Ana", "Luis"]),
            ({"professional__isnull": "True"}, ["No professional"]),
            ({"status__exact": "booked"}, ["Ana", "Luis", "No professional"]),
        ],
    )
    def test_only_those_of_the_changelists_filter(
        self, admin_client, ana, luis, query, titles
    ):
        ids = {"ana": ana.pk, "luis": luis.pk}
        query = {key: value.format(**ids) for key, value in query.items()}
        html = admin_client.get(f"{APPOINTMENTS}calendar/", query).content.decode()
        assert [item["title"] for item in config(html)["resources"]] == titles

    def test_its_label_of_none(self, rf, ana):
        class Named(AppointmentAdmin):
            calendar_resource_empty_label = "Anyone"

        request = rf.get("/")
        assert Named(Appointment, admin.site).get_calendar_resources(request)[-1] == {
            "id": NO_RESOURCE,
            "title": "Anyone",
        }

    def test_the_events_resource(self, admin_client, maria):
        Appointment.objects.create(client="Pedro", start=at(12), minutes=30)
        events = booked(admin_client.get(f"{APPOINTMENTS}calendar/events/", DAY).json())
        by_title = {event["title"]: event["resourceIds"] for event in events}
        assert by_title == {
            "María": [str(maria.professional_id)],
            "Pedro": [NO_RESOURCE],
        }

    def test_moved_to_another(self, admin_client, maria, luis):
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {
                "pk": maria.pk,
                "start": "2026-10-29T17:00:00",  # In Luis' hours.
                "end": "2026-10-29T17:45:00",
                "resource": str(luis.pk),
                "resource_from": str(maria.professional_id),
            },
        )
        assert response.status_code == 200
        assert response.json()["event"]["resourceIds"] == [str(luis.pk)]
        maria.refresh_from_db()
        assert (maria.professional, maria.start, maria.minutes) == (luis, at(17), 45)
        assert json.loads(LogEntry.objects.get().change_message) == [
            {"changed": {"fields": ["start", "minutes", "professional"]}}
        ]

    def test_moved_to_none(self, admin_client, maria):
        admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {"pk": maria.pk, "start": "2026-10-29T09:00:00", "resource": NO_RESOURCE},
        )
        maria.refresh_from_db()
        assert maria.professional is None

    def test_not_to_one_it_cant_be_in(self, admin_client, maria):
        retired = Professional.objects.create(name="Retired", active=False)
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {"pk": maria.pk, "start": "2026-10-29T09:00:00", "resource": retired.pk},
        )
        assert response.status_code == 400
        assert response.json() == {"error": "Unknown professional."}

    def test_not_when_its_resource_is_fixed(
        self, admin_client, maria, luis, monkeypatch
    ):
        model_admin = admin.site._registry[Appointment]
        monkeypatch.setattr(model_admin, "calendar_resource_editable", False)
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {"pk": maria.pk, "start": "2026-10-29T09:00:00", "resource": luis.pk},
        )
        assert response.status_code == 400
        assert response.json() == {
            "error": "It can't be moved to another professional."
        }
        html = admin_client.get(f"{APPOINTMENTS}calendar/").content.decode()
        assert config(html)["resource"]["editable"] is False

    def test_the_add_page_in_its_column(self, admin_client, luis):
        response = admin_client.get(
            reverse("admin:agenda_appointment_add"),
            {
                "start": "2026-10-29T10:00:00",
                "end": "2026-10-29T11:30:00",
                "professional": luis.pk,
            },
        )
        initial = response.context["adminform"].form.initial
        assert (initial["start"], initial["minutes"]) == (at(10), 90)
        assert str(initial["professional"]) == str(luis.pk)


class TestTheCalendarsQueryset:
    def test_restricts_the_calendar_only(self, admin_client, maria):
        Appointment.objects.create(
            client="Old", start=at(15), minutes=30, status="cancelled"
        )
        events = booked(admin_client.get(f"{APPOINTMENTS}calendar/events/", DAY).json())
        assert [event["title"] for event in events] == ["María"]
        # The list has it.
        assert "Old" in admin_client.get(APPOINTMENTS).content.decode()

    def test_and_its_moves(self, admin_client):
        old = Appointment.objects.create(
            client="Old", start=at(15), minutes=30, status="cancelled"
        )
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {"pk": old.pk, "start": "2026-10-29T16:00:00"},
        )
        assert response.status_code == 404

    def test_an_unknown_filter_on_its_page(self, admin_client):
        response = admin_client.get(f"{APPOINTMENTS}calendar/", {"nothing": "1"})
        assert response.status_code == 200
        assert response.context["cl"] is None

    def test_its_page_shows_the_changelists_filters_and_search(self, admin_client, ana):
        html = admin_client.get(
            f"{APPOINTMENTS}calendar/", {"professional__id__exact": ana.pk}
        ).content.decode()
        assert 'id="changelist-filter"' in html
        assert 'id="searchbar"' in html
        assert "Clear all filters" in html
        assert "data-django-ec-calendar-keep-state" in html

    def test_without_them(self, admin_client, monkeypatch):
        monkeypatch.setattr(
            admin.site._registry[Appointment], "calendar_filters", False
        )
        html = admin_client.get(f"{APPOINTMENTS}calendar/").content.decode()
        assert 'id="changelist-filter"' not in html

    @pytest.mark.parametrize("django", [(6, 0), (5, 2)])
    def test_filters_where_the_admin_puts_them(self, admin_client, monkeypatch, django):
        monkeypatch.setattr("django.VERSION", django)
        html = admin_client.get(f"{APPOINTMENTS}calendar/").content.decode()
        # Django 6: in the container, before the content; before, after it.
        before = html.index('id="changelist-filter"') < html.index(
            'id="django-ec-calendar"'
        )
        assert before is (django >= (6, 0))


class TestManyToMany:
    @pytest.fixture
    def people(self, db):
        return Person.objects.create(name="Ana"), Person.objects.create(name="Luis")

    @pytest.fixture
    def meeting(self, people):
        meeting = Meeting.objects.create(
            title="Kick-off",
            start=at(10),
            length=datetime.timedelta(hours=1),
            host=people[0],
            day=datetime.date(2026, 10, 29),
            kind="call",
        )
        meeting.attendees.add(*people)
        return meeting

    def test_in_each_of_its_resources_with_its_details(
        self, admin_client, meeting, people
    ):
        [event] = admin_client.get(f"{MEETINGS}calendar/events/", DAY).json()
        assert event["resourceIds"] == [str(people[0].pk), str(people[1].pk)]
        assert event["end"] == "2026-10-29T11:00:00"
        assert event["extendedProps"]["details"] == [
            {"label": "host", "value": "Ana"},
            {"label": "online", "value": "No"},
            {"label": "day", "value": "Oct. 29, 2026"},
            {"label": "kind", "value": "Call"},
            {"label": "Place", "value": "Office"},
        ]
        assert event["extendedProps"]["url"] == reverse(
            "calendars:calapp_meeting_change", args=[meeting.pk]
        )

    def test_none_and_resources_of_a_blank_one(self, admin_client, people):
        Meeting.objects.create(title="Alone", start=at(12))
        [event] = admin_client.get(f"{MEETINGS}calendar/events/", DAY).json()
        assert event["resourceIds"] == [NO_RESOURCE]
        assert "end" not in event
        resources = ByAttendees(Meeting, calendars).get_calendar_resources(
            RequestFactory().get("/")
        )
        assert resources[-1] == {"id": NO_RESOURCE, "title": "No attendees"}

    def test_moved_from_one_to_another(self, admin_client, meeting, people):
        carla = Person.objects.create(name="Carla")
        response = admin_client.post(
            f"{MEETINGS}calendar/move/",
            {
                "pk": meeting.pk,
                "start": "2026-10-29T12:00:00",
                "end": "2026-10-29T12:30:00",
                "resource": carla.pk,
                "resource_from": people[1].pk,
            },
        )
        assert response.status_code == 200
        meeting.refresh_from_db()
        assert set(meeting.attendees.all()) == {people[0], carla}
        assert meeting.length == datetime.timedelta(minutes=30)
        assert json.loads(LogEntry.objects.get().change_message) == [
            {"changed": {"fields": ["start", "length", "attendees"]}}
        ]

    def test_from_none_and_to_none(self, admin_client, people):
        alone = Meeting.objects.create(title="Alone", start=at(12))
        admin_client.post(
            f"{MEETINGS}calendar/move/",
            {
                "pk": alone.pk,
                "start": "2026-10-29T12:00:00",
                "resource": people[0].pk,
                "resource_from": NO_RESOURCE,
            },
        )
        assert list(alone.attendees.all()) == [people[0]]
        admin_client.post(
            f"{MEETINGS}calendar/move/",
            {
                "pk": alone.pk,
                "start": "2026-10-29T12:00:00",
                "resource": NO_RESOURCE,
                "resource_from": people[0].pk,
            },
        )
        assert list(alone.attendees.all()) == []


class TestChoices:
    class ByKind(CalendarSource):
        model = Meeting
        calendar_start_field = "start"
        calendar_resource_field = "kind"

    def test_its_choices_and_none(self, db):
        resources = self.ByKind().get_calendar_resources(RequestFactory().get("/"))
        assert resources == [
            {"id": "call", "title": "Call"},
            {"id": "visit", "title": "Visit"},
            {"id": NO_RESOURCE, "title": "No kind"},
        ]

    def test_an_events_and_back(self, db):
        meeting = Meeting.objects.create(title="x", start=at(9), kind="visit")
        assert self.ByKind().get_calendar_resource_ids(meeting) == ["visit"]
        meeting.kind = ""
        assert self.ByKind().get_calendar_resource_ids(meeting) == [NO_RESOURCE]
        assert self.ByKind().resource_value(NO_RESOURCE) == ""
        assert self.ByKind().resource_value("call") == "call"

    def test_a_foreign_key_that_isnt_null(self, db):
        class ByHost(CalendarSource):
            model = Meeting
            calendar_start_field = "start"
            calendar_resource_field = "title"

        with pytest.raises(ImproperlyConfigured, match="foreign key, a many-to-many"):
            ByHost().get_calendar_resources(RequestFactory().get("/"))


class TestDurations:
    def test_in_minutes(self, maria):
        source = AppointmentAdmin(Appointment, admin.site)
        assert source.get_calendar_event_end(maria) == at(9, 45)
        assert source.has_end
        assert source.moved_values("2026-10-29T10:00:00", "2026-10-29T10:20:00") == {
            "start": at(10),
            "minutes": 20,
        }
        # Without an end: as it was.
        assert source.moved_values("2026-10-29T10:00:00", "") == {"start": at(10)}

    def test_looks_back_as_far_as_the_longest(self, admin_client, ana):
        Appointment.objects.create(
            client="Night", professional=ana, start=at(23, day=28), minutes=120
        )
        Appointment.objects.create(
            client="Long ago", professional=ana, start=at(9, day=20), minutes=30
        )
        events = booked(admin_client.get(f"{APPOINTMENTS}calendar/events/", DAY).json())
        assert [event["title"] for event in events] == ["Night"]

    def test_none(self, db):
        meeting = Meeting(title="x", start=at(9))
        assert ByAttendees(Meeting, calendars).get_calendar_event_end(meeting) is None


class TestBackToTheCalendar:
    def test_after_changing_one(self, admin_client, maria):
        calendar = (
            f"{APPOINTMENTS}calendar/?ec-view=resourceTimeGridDay&ec-date=2026-10-29"
        )
        change = reverse("admin:agenda_appointment_change", args=[maria.pk])
        response = admin_client.post(
            f"{change}?_ec_calendar={calendar.replace('&', '%26').replace('?', '%3F')}",
            {
                "client": "María",
                "professional": maria.professional_id,
                "start_0": "2026-10-29",
                "start_1": "09:00:00",
                "minutes": 45,
                "status": "booked",
            },
        )
        assert response.status_code == 302
        assert response.url == calendar

    def test_after_adding_one(self, admin_client):
        calendar = f"{APPOINTMENTS}calendar/"
        response = admin_client.post(
            f"{reverse('admin:agenda_appointment_add')}?_ec_calendar={calendar}",
            {
                "client": "New",
                "start_0": "2026-10-29",
                "start_1": "09:00:00",
                "minutes": 30,
                "status": "booked",
            },
        )
        assert response.url == calendar

    @pytest.mark.parametrize(
        "url",
        ["https://elsewhere.example/admin/agenda/appointment/calendar/", "/admin/"],
    )
    def test_only_to_its_calendar(self, admin_client, maria, url):
        change = reverse("admin:agenda_appointment_change", args=[maria.pk])
        response = admin_client.post(
            f"{change}?_ec_calendar={url}",
            {
                "client": "María",
                "start_0": "2026-10-29",
                "start_1": "09:00:00",
                "minutes": 45,
                "status": "booked",
            },
        )
        assert response.url == reverse("admin:agenda_appointment_changelist")

    def test_its_parameters_arent_filters(self, admin_client, maria):
        response = admin_client.get(
            f"{APPOINTMENTS}calendar/events/",
            {
                **DAY,
                "ec-view": "listWeek",
                "ec-date": "2026-10-29",
                "_ec_calendar": "/",
            },
        )
        assert response.status_code == 200


def test_display_value():
    assert display_value(None) == ""
    assert display_value("") == ""
    assert display_value(True) == "Yes"
    assert display_value(3) == "3"
    assert display_value(at(10)).startswith("Oct. 29, 2026")


def test_a_resource_one_must_have(db):
    from agenda.models import Booking, Room

    class ByRoom(CalendarSource):
        model = Booking
        calendar_start_field = "start"
        calendar_resource_field = "room"

    room = Room.objects.create(name="Blue")
    resources = ByRoom().get_calendar_resources(RequestFactory().get("/"))
    assert resources == [{"id": str(room.pk), "title": "Blue"}]  # No "none".
    booking = Booking(title="x", room=room, start=at(9), end=at(10))
    assert ByRoom().get_calendar_resource_ids(booking) == [str(room.pk)]


def test_choices_by_the_changelists_filter(admin_client, rf):
    class ByKind(ByAttendees):
        calendar_resource_field = "kind"

    request = rf.get("/", {"kind__exact": "visit"})
    resources = ByKind(Meeting, calendars).get_calendar_resources(request)
    assert resources == [{"id": "visit", "title": "Visit"}]
