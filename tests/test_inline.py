"""CalendarInline (an object's calendar in its change page), and the date
picker."""

import datetime
import json
import re
import zoneinfo

import pytest
from agenda.admin import AppointmentCalendarInline
from agenda.models import Appointment, Booking, Professional
from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ImproperlyConfigured
from django.template import Context, Template
from django.test import Client, RequestFactory
from django.urls import reverse

from django_ec_calendar import CalendarInline

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")


def at(hour):
    return datetime.datetime(2026, 10, 29, hour, tzinfo=MADRID)


def config(html, element="appointment-calendar"):
    match = re.search(
        rf'<script id="{element}-config" type="application/json">(.*?)</script>',
        html,
    )
    return json.loads(match.group(1)) if match else None


@pytest.fixture
def ana(db):
    return Professional.objects.create(name="Ana")


@pytest.fixture
def maria(ana):
    return Appointment.objects.create(
        client="María", professional=ana, start=at(9), minutes=60
    )


def change(professional):
    return reverse("admin:agenda_professional_change", args=[professional.pk])


class TestInTheObjectsPage:
    def test_its_calendar_of_its_objects(self, admin_client, ana, maria):
        html = admin_client.get(change(ana)).content.decode()
        assert "django-ec-calendar-inline" in html
        assert "event-calendar.min.js" in html
        data = config(html)
        assert data["params"] == {"professional__id__exact": str(ana.pk)}
        assert data["view"] == "timeGridWeek"
        assert data["views"] == ["timeGridWeek", "timeGridDay", "listWeek"]
        assert data["urlState"] is False
        assert data["add"] == (
            f"{reverse('admin:agenda_appointment_add')}?professional={ana.pk}"
        )
        # Its column only, of the appointments' resources.
        assert [item["id"] for item in data["resources"]] == [str(ana.pk)]
        # The appointments' admin's.
        assert data["moveMode"] == "batch"
        events = admin_client.get(data["events"], {**data["params"]}).json()
        assert [event["title"] for event in events if event.get("title")] == ["María"]

    def test_not_before_it_is_saved(self, admin_client, db):
        html = admin_client.get(
            reverse("admin:agenda_professional_add")
        ).content.decode()
        assert "Save it first to see its calendar." in html
        assert config(html) is None

    def test_the_objects_form_still_saves(self, admin_client, ana, maria):
        response = admin_client.post(
            change(ana),
            {
                "name": "Ana López",
                "active": "on",
                "appointments-TOTAL_FORMS": "0",
                "appointments-INITIAL_FORMS": "0",
                "appointments-MIN_NUM_FORMS": "0",
                "appointments-MAX_NUM_FORMS": "0",
            },
        )
        assert response.status_code == 302
        ana.refresh_from_db()
        assert ana.name == "Ana López"
        assert Appointment.objects.get() == maria  # Untouched.

    def test_for_who_may_see_the_calendar(self, ana):
        clerk = User.objects.create_user("clerk", is_staff=True)
        clerk.user_permissions.add(
            Permission.objects.get(codename="change_professional")
        )
        client = Client()
        client.force_login(clerk)
        html = client.get(change(ana)).content.decode()
        assert "django-ec-calendar-inline" not in html
        clerk.user_permissions.add(Permission.objects.get(codename="view_appointment"))
        client.force_login(User.objects.get(pk=clerk.pk))
        data = config(client.get(change(ana)).content.decode())
        assert (data["add"], data["move"]) == (None, None)

    def test_its_admins_own_views(self, rf, ana):
        class Plain(AppointmentCalendarInline):
            calendar_view = None
            calendar_views = None

        request = rf.get("/")
        request.user = User.objects.create_superuser("root", "r@x.y", "pw")
        inline = Plain(Professional, admin.site)
        calendar = inline.get_calendar(request, ana)
        assert calendar.config["view"] == "resourceTimeGridDay"
        assert calendar.config["views"] == [
            "resourceTimeGridDay",
            "resourceTimeGridWeek",
            "listWeek",
        ]

    def test_back_to_the_objects_page_after_a_save(self, admin_client, ana, maria):
        page = change(ana)
        appointment = reverse("admin:agenda_appointment_change", args=[maria.pk])
        response = admin_client.post(
            f"{appointment}?_ec_calendar={page}",
            {
                "client": "María",
                "professional": ana.pk,
                "start_0": "2026-10-29",
                "start_1": "10:00:00",
                "minutes": 60,
                "status": "booked",
            },
        )
        assert response.url == page

    def test_without_a_calendar_admin(self, db):
        from tests.calapp.models import Meeting, Person

        class Meetings(CalendarInline):
            model = Meeting  # Not of admin.site's.
            fk_name = "host"

        with pytest.raises(ImproperlyConfigured, match="isn't a CalendarAdminMixin"):
            Meetings(Person, admin.site).get_calendar_admin()

    def test_without_its_admins_index(self, rf, ana):
        site = admin.AdminSite(name="nowhere")  # Its URLs aren't included.
        model_admin = type(admin.site._registry[Appointment])(Appointment, site)
        request = rf.get("/", {"_ec_calendar": "/admin/"})
        assert model_admin._calendar_return(request) is None


class TestDatePicker:
    def test_on_by_default(self, admin_client):
        html = admin_client.get("/admin/agenda/booking/calendar/").content.decode()
        assert config(html, "django-ec-calendar")["datePicker"] is True
        assert config(html, "django-ec-calendar")["texts"]["goToDate"] == "Go to a date"

    def test_off(self, admin_client, monkeypatch):
        model_admin = admin.site._registry[Booking]
        monkeypatch.setattr(model_admin, "calendar_date_picker", False)
        html = admin_client.get("/admin/agenda/booking/calendar/").content.decode()
        assert config(html, "django-ec-calendar")["datePicker"] is False

    def test_in_the_tag(self):
        html = Template(
            '{% load ec_calendar %}{% ec_calendar "/e/" id="t" date_picker=False %}'
        ).render(Context({"request": RequestFactory().get("/")}))
        assert config(html, "t")["datePicker"] is False
