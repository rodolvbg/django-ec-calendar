"""The URL's parameters with the calendar's view and date, and its return
parameter: their names, and the views'."""

import datetime
import json
import re
import zoneinfo

import pytest
from agenda.models import Appointment, Professional
from django.contrib import admin
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
APPOINTMENTS = "/admin/agenda/appointment/"


def config(html, element="django-ec-calendar"):
    match = re.search(
        rf'<script id="{element}-config" type="application/json">(.*?)</script>',
        html,
    )
    return json.loads(match.group(1))


@pytest.fixture
def renamed(monkeypatch):
    model_admin = admin.site._registry[Appointment]
    monkeypatch.setattr(
        model_admin, "calendar_url_params", {"view": "vista", "date": "fecha"}
    )
    monkeypatch.setattr(
        model_admin, "calendar_url_views", {"resourceTimeGridDay": "dia"}
    )
    monkeypatch.setattr(model_admin, "calendar_return_param", "volver")
    return model_admin


def test_by_default(admin_client):
    data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
    assert data["urlParams"] == {
        "view": "ec-view",
        "date": "ec-date",
        "resources": "ec-resources",
    }
    assert data["urlViews"] == {}
    assert data["returnParam"] == "_ec_calendar"


def test_their_names_and_the_views(admin_client, renamed):
    data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
    assert data["urlParams"] == {
        "view": "vista",
        "date": "fecha",
        "resources": "ec-resources",
    }
    assert data["urlViews"] == {"resourceTimeGridDay": "dia"}
    assert data["returnParam"] == "volver"


def test_only_one_named_the_other_by_default(admin_client, monkeypatch):
    model_admin = admin.site._registry[Appointment]
    monkeypatch.setattr(model_admin, "calendar_url_params", {"date": "fecha"})
    data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
    assert data["urlParams"] == {
        "view": "ec-view",
        "date": "fecha",
        "resources": "ec-resources",
    }


def test_theyre_not_filters(admin_client, renamed, db):
    query = {"vista": "dia", "fecha": "2026-10-29", "volver": "/admin/"}
    page = admin_client.get(f"{APPOINTMENTS}calendar/", query)
    assert page.status_code == 200
    data = config(page.content.decode())
    assert data["params"] == {}  # Not the changelist's.
    events = admin_client.get(
        f"{APPOINTMENTS}calendar/events/",
        {**query, "start": "2026-10-29T00:00:00", "end": "2026-10-30T00:00:00"},
    )
    assert events.status_code == 200
    # The defaults are filters now: the changelist doesn't know them.
    response = admin_client.get(
        f"{APPOINTMENTS}calendar/events/", {"ec-view": "listWeek"}
    )
    assert response.status_code == 400


def test_back_by_its_return_parameter(admin_client, renamed):
    ana = Professional.objects.create(name="Ana")
    maria = Appointment.objects.create(
        client="María",
        professional=ana,
        start=datetime.datetime(2026, 10, 29, 9, tzinfo=MADRID),
        minutes=60,
    )
    page = reverse("admin:agenda_professional_change", args=[ana.pk])
    response = admin_client.post(
        f"{reverse('admin:agenda_appointment_change', args=[maria.pk])}?volver={page}",
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


def test_in_the_tag():
    html = Template(
        "{% load ec_calendar %}"
        '{% ec_calendar "/e/" id="t" view_param="vista" date_param="fecha" %}'
    ).render(Context({"request": RequestFactory().get("/")}))
    assert config(html, "t")["urlParams"] == {"view": "vista", "date": "fecha"}


@pytest.fixture
def translated(monkeypatch, settings):
    """Its names translated (gettext_lazy): Spanish and English."""
    from django.utils.translation import gettext_lazy

    settings.LANGUAGES = [("en", "English"), ("es", "Spanish")]
    model_admin = admin.site._registry[Appointment]
    monkeypatch.setattr(
        model_admin,
        "calendar_url_params",
        {"view": gettext_lazy("Week"), "date": gettext_lazy("Day")},
    )
    monkeypatch.setattr(
        model_admin, "calendar_url_views", {"listWeek": gettext_lazy("List")}
    )
    monkeypatch.setattr(model_admin, "calendar_return_param", gettext_lazy("Today"))
    return model_admin


def test_translated_in_the_active_language(admin_client, translated):
    from django.utils.translation import override

    with override("es"):
        data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
    assert data["urlParams"] == {
        "view": "Semana",
        "date": "Día",
        "resources": "ec-resources",
    }
    assert data["urlViews"] == {"listWeek": "Lista"}
    assert data["returnParam"] == "Hoy"
    # The other languages', read too.
    assert data["urlAliases"] == {
        "params": {"view": ["Week"], "date": ["Day"]},
        "views": {"listWeek": ["List"]},
        "resources": {},
    }


def test_another_languages_arent_filters(admin_client, translated, db):
    """A language switched keeps the query: still not filters."""
    from django.utils.translation import override

    query = {"Week": "List", "Day": "2026-10-29", "Today": "/admin/"}
    with override("es"):
        page = admin_client.get(f"{APPOINTMENTS}calendar/", query)
        assert page.status_code == 200
        events = admin_client.get(
            f"{APPOINTMENTS}calendar/events/",
            {**query, "start": "2026-10-29T00:00:00", "end": "2026-10-30T00:00:00"},
        )
    assert events.status_code == 200


def test_back_by_another_languages_return_parameter(admin_client, translated):
    from django.utils.translation import override

    ana = Professional.objects.create(name="Ana")
    maria = Appointment.objects.create(
        client="María",
        professional=ana,
        start=datetime.datetime(2026, 10, 29, 9, tzinfo=MADRID),
        minutes=60,
    )
    page = reverse("admin:agenda_professional_change", args=[ana.pk])
    with override("es"):
        response = admin_client.post(
            f"{reverse('admin:agenda_appointment_change', args=[maria.pk])}"
            f"?Today={page}",
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


def test_without_a_return_parameter(admin_client, monkeypatch):
    model_admin = admin.site._registry[Appointment]
    monkeypatch.setattr(model_admin, "calendar_return_param", None)
    data = config(admin_client.get(f"{APPOINTMENTS}calendar/").content.decode())
    assert data["returnParam"] is None
