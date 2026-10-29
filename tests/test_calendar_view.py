"""CalendarView, Calendar and CalendarMixin: a calendar out of the admin."""

import datetime
import json
import re
import zoneinfo

import pytest
from agenda.models import Appointment, Professional
from agenda.views import ProfessionalAgenda
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ImproperlyConfigured
from django.template import Context, Template
from django.test import Client, RequestFactory
from django.urls import resolve, reverse

from django_ec_calendar import Calendar, CalendarMixin, CalendarView

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
DAY = {"start": "2026-10-29T00:00:00", "end": "2026-10-30T00:00:00"}


def at(hour):
    return datetime.datetime(2026, 10, 29, hour, tzinfo=MADRID)


def config(html, element):
    match = re.search(
        rf'<script id="{element}" type="application/json">(.*?)</script>', html
    )
    return json.loads(match.group(1))


@pytest.fixture
def ana(db):
    return Professional.objects.create(name="Ana")


@pytest.fixture
def maria(ana):
    return Appointment.objects.create(
        client="María", professional=ana, start=at(9), minutes=60
    )


@pytest.fixture
def luis_appointment(db):
    luis = Professional.objects.create(name="Luis")
    return Appointment.objects.create(
        client="Jorge", professional=luis, start=at(10), minutes=30
    )


_users = iter(range(1, 1000))


def user(*codenames):
    made = User.objects.create_user(f"clerk{next(_users)}")
    made.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    client = Client()
    client.force_login(made)
    return client


class TestItsURLs:
    def test_a_page_and_its_endpoints(self, ana):
        base = reverse("agenda", args=[ana.pk])
        assert base == f"/agenda/{ana.pk}/"
        for name, suffix in (
            ("events", "events/"),
            ("move", "move/"),
            ("moves", "moves/"),
        ):
            assert reverse(f"agenda-{name}", args=[ana.pk]) == f"{base}{suffix}"
            assert resolve(f"{base}{suffix}").func.view_initkwargs["action"] == name

    def test_wrong_methods(self, admin_client, ana):
        base = reverse("agenda", args=[ana.pk])
        assert admin_client.post(base).status_code == 405
        assert admin_client.get(f"{base}move/").status_code == 405
        assert admin_client.post(f"{base}events/").status_code == 405


class TestItsPage:
    def test_its_calendar(self, admin_client, ana):
        response = admin_client.get(reverse("agenda", args=[ana.pk]))
        html = response.content.decode()
        assert "<h1>Agenda: Ana</h1>" in html
        assert "event-calendar.min.js" in html
        element = re.search(r'data-django-ec-calendar="([^"]+)"', html).group(1)
        data = config(html, element)
        base = f"/agenda/{ana.pk}/"
        assert data["events"] == f"{base}events/"
        assert data["move"] == f"{base}move/"
        assert data["moves"] is None  # "confirm".
        assert data["moveMode"] == "confirm"
        assert data["add"] == reverse("admin:agenda_appointment_add")
        assert data["returnParam"] is None
        assert data["view"] == "timeGridWeek"
        assert data["options"] == {"slotMinTime": "08:00", "slotMaxTime": "20:00"}

    def test_by_the_users_permissions(self, ana):
        url = reverse("agenda", args=[ana.pk])
        assert user().get(url).status_code == 403
        assert Client().get(url).status_code == 403
        html = user("view_appointment").get(url).content.decode()
        element = re.search(r'data-django-ec-calendar="([^"]+)"', html).group(1)
        data = config(html, element)
        # Only seeing it: nothing to move, nor to add.
        assert (data["move"], data["moveMode"], data["add"]) == (None, "off", None)

    def test_its_title_by_default(self, rf, db):
        class Appointments(CalendarView):
            model = Appointment
            calendar_start_field = "start"

        assert Appointments().get_title() == "Appointments"
        assert Appointments().get_queryset().model is Appointment

        class Titled(Appointments):
            title = "Ours"

        assert Titled().get_title() == "Ours"


class TestItsEvents:
    def test_only_its_professionals(self, admin_client, maria, luis_appointment):
        events = admin_client.get(
            reverse("agenda-events", args=[maria.professional_id]), DAY
        ).json()
        assert [(e["title"], e["editable"]) for e in events] == [("María", True)]
        assert events[0]["extendedProps"]["details"] == [
            {"label": "status", "value": "Booked"}
        ]

    def test_by_the_users_permissions(self, maria):
        url = reverse("agenda-events", args=[maria.professional_id])
        assert user().get(url, DAY).status_code == 403
        [event] = user("view_appointment").get(url, DAY).json()
        assert event["editable"] is False


class TestItsMoves:
    def test_saved(self, admin_client, maria):
        response = admin_client.post(
            reverse("agenda-move", args=[maria.professional_id]),
            {
                "pk": maria.pk,
                "start": "2026-10-29T11:00:00",
                "end": "2026-10-29T11:30:00",
            },
        )
        assert response.status_code == 200
        maria.refresh_from_db()
        assert (maria.start, maria.minutes) == (at(11), 30)
        assert not LogEntry.objects.exists()  # Not the admin's.

    def test_not_another_professionals(self, admin_client, maria, luis_appointment):
        response = admin_client.post(
            reverse("agenda-move", args=[maria.professional_id]),
            {"pk": luis_appointment.pk, "start": "2026-10-29T11:00:00"},
        )
        assert response.status_code == 404

    def test_by_the_users_permissions(self, maria):
        response = user("view_appointment").post(
            reverse("agenda-move", args=[maria.professional_id]),
            {"pk": maria.pk, "start": "2026-10-29T11:00:00"},
        )
        assert response.status_code == 403

    def test_several_together(self, admin_client, maria, monkeypatch):
        monkeypatch.setattr(ProfessionalAgenda, "calendar_move_mode", "batch")
        response = admin_client.post(
            reverse("agenda-moves", args=[maria.professional_id]),
            json.dumps(
                {"moves": [{"pk": maria.pk, "start": "2026-10-29T12:00:00", "end": ""}]}
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        maria.refresh_from_db()
        assert maria.start == at(12)


class TestOnAnotherPage:
    def test_its_calendar_for_it(self, ana):
        request = RequestFactory().get("/elsewhere/")
        request.user = User.objects.create_superuser("root", "r@x.y", "pw")
        calendar = ProfessionalAgenda.calendar_for(
            request, f"/agenda/{ana.pk}", pk=ana.pk
        )
        assert calendar.config["events"] == f"/agenda/{ana.pk}/events/"
        assert "event-calendar.min.js" in str(calendar.media)
        html = str(calendar)
        assert f'id="{calendar.id}"' in html
        assert (
            config(html, f"{calendar.id}-config")["move"] == f"/agenda/{ana.pk}/move/"
        )


class TestCalendar:
    def test_rendered_in_a_template(self):
        calendar = Calendar({"events": "/e/"}, id="mine")
        html = Template("{{ calendar }}").render(Context({"calendar": calendar}))
        assert 'id="mine"' in html
        assert config(html, "mine-config") == {"events": "/e/"}
        assert calendar.__html__() == calendar.render()

    def test_its_own_id(self):
        first, second = Calendar({}), Calendar({})
        assert first.id != second.id
        assert first.id.startswith("ec-calendar-")


class TestCalendarMixin:
    class Plain(CalendarMixin):
        model = Appointment
        calendar_start_field = "start"

    def test_all_by_default_and_where_it_is_its_own(self, maria):
        assert list(self.Plain().get_calendar_queryset(RequestFactory().get("/"))) == [
            maria
        ]
        with pytest.raises(NotImplementedError):
            self.Plain().get_calendar_urls(RequestFactory().get("/"))

    def test_without_a_user_nothing(self, db):
        request = RequestFactory().get("/")
        assert self.Plain().has_calendar_view_permission(request) is False

    def test_the_initial_values_of_its_add_page(self, db):
        class ByProfessional(self.Plain):
            calendar_duration_field = "minutes"
            calendar_resource_field = "professional"

        request = RequestFactory().get(
            "/",
            {
                "start": "2026-10-29T09:00:00",
                "end": "2026-10-29T10:30:00",
                "professional": "3",
            },
        )
        assert ByProfessional().get_calendar_initial(request) == {
            "start": at(9),
            "minutes": 90,
            "professional": "3",
        }
        assert ByProfessional().get_calendar_initial(RequestFactory().get("/")) == {}


class TestCalendarViewConfiguration:
    def test_no_objects(self, db):
        class Nothing(CalendarView):
            calendar_start_field = "start"

        with pytest.raises(ImproperlyConfigured, match="needs a model, a queryset"):
            Nothing().get_queryset()

    def test_a_queryset(self, maria):
        class Some(CalendarView):
            queryset = Appointment.objects.filter(client="María")
            calendar_start_field = "start"

        assert list(Some().get_queryset()) == [maria]
        assert Some().get_source_model() is Appointment

    def test_its_add_page_by_its_path_or_none(self, rf):
        class ByPath(ProfessionalAgenda):
            calendar_add_url = "/appointments/new/"

        class NoAdding(ProfessionalAgenda):
            calendar_add_url = None

        request = rf.get("/")
        assert ByPath().get_calendar_add_url(request) == "/appointments/new/"
        assert NoAdding().get_calendar_add_url(request) is None
        request.user = User(is_superuser=True, is_active=True)
        assert NoAdding().has_calendar_add_permission(request) is False


def test_a_display_method_of_no_field(db):
    from django_ec_calendar import CalendarSource
    from tests.calapp.models import Meeting

    class Meetings(CalendarSource):
        model = Meeting
        calendar_start_field = "start"
        calendar_detail_fields = ("get_kind_display", "get_place_display")

    meeting = Meeting(title="x", start=at(9), kind="call")
    assert Meetings().get_calendar_details(RequestFactory().get("/"), meeting) == [
        {"label": "kind", "value": "Call"},
        {"label": "Where", "value": "Office"},
    ]


def test_an_event_one_may_not_open(admin_client, maria, monkeypatch):
    from django.contrib import admin

    model_admin = admin.site._registry[Appointment]
    monkeypatch.setattr(
        model_admin,
        "has_view_or_change_permission",
        lambda request, obj=None: obj is None,
    )
    request = RequestFactory().get("/")
    assert model_admin.get_calendar_event_url(request, maria) is None
