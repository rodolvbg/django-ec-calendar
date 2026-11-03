"""Undoing a saved move: its configuration, and the check that what's
undone hasn't changed since (``expect_*`` in a move)."""

import datetime
import json
import re
import zoneinfo

import pytest
from agenda.models import Appointment, Booking, Professional, Room
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.utils import translation

from django_ec_calendar.config import calendar_texts

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
BOOKINGS = "/admin/agenda/booking/"
MOVE = f"{BOOKINGS}calendar/move/"
APPOINTMENTS = "/admin/agenda/appointment/"
MOVES = f"{APPOINTMENTS}calendar/moves/"


def at(hour, minute=0):
    return datetime.datetime(2026, 10, 29, hour, minute, tzinfo=MADRID)


def config(html):
    match = re.search(
        r'<script id="django-ec-calendar-config" type="application/json">'
        r"(.*?)</script>",
        html,
    )
    return json.loads(match.group(1))


@pytest.fixture
def blue(db):
    return Room.objects.create(name="Blue", color="#00f")


@pytest.fixture
def call(blue):
    return Booking.objects.create(title="Call", room=blue, start=at(9), end=at(10))


@pytest.fixture
def ana(db):
    return Professional.objects.create(name="Ana")


@pytest.fixture
def luis(db):
    return Professional.objects.create(name="Luis")


@pytest.fixture
def maria(ana):
    return Appointment.objects.create(
        client="María", professional=ana, start=at(9), minutes=60
    )


def move(client, call, start, end, **extra):
    return client.post(MOVE, {"pk": call.pk, "start": start, "end": end, **extra})


class TestConfiguration:
    def test_on_by_default_for_ten_seconds(self, admin_client):
        html = admin_client.get(f"{BOOKINGS}calendar/").content.decode()
        assert config(html)["undoSeconds"] == 10

    def test_its_seconds(self, admin_client, monkeypatch):
        monkeypatch.setattr(admin.site._registry[Booking], "calendar_undo_seconds", 30)
        html = admin_client.get(f"{BOOKINGS}calendar/").content.decode()
        assert config(html)["undoSeconds"] == 30

    def test_off(self, admin_client, monkeypatch):
        monkeypatch.setattr(admin.site._registry[Booking], "calendar_undo", False)
        html = admin_client.get(f"{BOOKINGS}calendar/").content.decode()
        assert config(html)["undoSeconds"] == 0

    def test_never_negative(self, admin_client, monkeypatch):
        monkeypatch.setattr(admin.site._registry[Booking], "calendar_undo_seconds", -5)
        html = admin_client.get(f"{BOOKINGS}calendar/").content.decode()
        assert config(html)["undoSeconds"] == 0

    def test_nothing_to_undo_without_moves(self, admin_client, monkeypatch):
        monkeypatch.setattr(admin.site._registry[Booking], "calendar_move_mode", "off")
        html = admin_client.get(f"{BOOKINGS}calendar/").content.decode()
        assert config(html)["undoSeconds"] == 0

    def test_nothing_to_undo_for_who_may_only_view(self, client, db):
        clerk = User.objects.create_user("clerk", is_staff=True)
        clerk.user_permissions.add(Permission.objects.get(codename="view_booking"))
        client.force_login(clerk)
        html = client.get(f"{BOOKINGS}calendar/").content.decode()
        assert config(html)["undoSeconds"] == 0

    def test_its_words(self):
        texts = calendar_texts()
        assert texts["undo"] == "Undo"
        assert texts["moved"] == "Moved “%(title)s”."
        assert texts["movedMany"]["one"] == "%(count)s event moved."
        assert texts["movedMany"]["other"] == "%(count)s events moved."

    def test_in_spanish(self):
        with translation.override("es"):
            texts = calendar_texts()
        assert texts["undo"] == "Deshacer"
        assert texts["moved"] == "Se movió «%(title)s»."
        assert texts["movedMany"]["other"] == "%(count)s eventos movidos."


class TestUndoingOne:
    """The move that undoes one is any other, with what the first left."""

    def test_the_opposite_move_when_nothing_changed(self, admin_client, call):
        done = move(admin_client, call, "2026-10-29T15:00:00", "2026-10-29T16:00:00")
        saved = done.json()["event"]
        undone = move(
            admin_client,
            call,
            "2026-10-29T09:00:00",
            "2026-10-29T10:00:00",
            expect_start=saved["start"],
            expect_end=saved["end"],
        )
        assert undone.status_code == 200
        call.refresh_from_db()
        assert (call.start, call.end) == (at(9), at(10))

    def test_logged_as_a_move_is(self, admin_client, call):
        done = move(admin_client, call, "2026-10-29T15:00:00", "2026-10-29T16:00:00")
        saved = done.json()["event"]
        move(
            admin_client,
            call,
            "2026-10-29T09:00:00",
            "2026-10-29T10:00:00",
            expect_start=saved["start"],
            expect_end=saved["end"],
        )
        assert LogEntry.objects.count() == 2

    def test_refused_when_it_changed_since(self, admin_client, call):
        done = move(admin_client, call, "2026-10-29T15:00:00", "2026-10-29T16:00:00")
        saved = done.json()["event"]
        Booking.objects.filter(pk=call.pk).update(start=at(17), end=at(18))
        undone = move(
            admin_client,
            call,
            "2026-10-29T09:00:00",
            "2026-10-29T10:00:00",
            expect_start=saved["start"],
            expect_end=saved["end"],
        )
        assert undone.status_code == 409
        assert undone.json() == {
            "error": "It was changed since, so this can't be undone."
        }
        call.refresh_from_db()
        assert call.start == at(17)  # Nobody's change was overwritten.

    def test_its_end_counts_too(self, admin_client, call):
        undone = move(
            admin_client,
            call,
            "2026-10-29T08:00:00",
            "2026-10-29T08:30:00",
            expect_start="2026-10-29T09:00:00",
            expect_end="2026-10-29T11:00:00",
        )
        assert undone.status_code == 409

    def test_without_expectations_it_is_any_other_move(self, admin_client, call):
        done = move(admin_client, call, "2026-10-29T15:00:00", "2026-10-29T16:00:00")
        assert done.status_code == 200

    def test_a_move_of_what_isnt_there_says_so_first(self, admin_client, call):
        response = admin_client.post(
            MOVE,
            {
                "pk": 999,
                "start": "2026-10-29T09:00:00",
                "end": "",
                "expect_start": "x",
            },
        )
        assert response.status_code == 404

    def test_in_spanish(self, admin_client, call):
        with translation.override("es"):
            response = admin_client.post(
                MOVE,
                {
                    "pk": call.pk,
                    "start": "2026-10-29T08:00:00",
                    "end": "2026-10-29T08:30:00",
                    "expect_start": "2000-01-01T00:00:00",
                },
                HTTP_ACCEPT_LANGUAGE="es",
            )
        assert response.status_code == 409
        assert response.json()["error"] == (
            "Se cambió después, así que no se puede deshacer."
        )


class TestUndoingAResource:
    def test_refused_when_its_resource_changed_since(
        self, admin_client, maria, ana, luis
    ):
        # Moved from Ana to Luis (by the one undone), and someone put it back.
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {
                "pk": maria.pk,
                "start": "2026-10-29T09:00:00",
                "end": "2026-10-29T10:00:00",
                "resource": ana.pk,
                "resource_from": luis.pk,
                "expect_resources": str(luis.pk),  # But it's with Ana.
            },
        )
        assert response.status_code == 409

    def test_undone_when_its_resource_is_as_it_was_left(
        self, admin_client, maria, ana, luis
    ):
        Appointment.objects.filter(pk=maria.pk).update(professional=luis, start=at(17))
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {
                "pk": maria.pk,
                "start": "2026-10-29T09:00:00",
                "end": "2026-10-29T10:00:00",
                "resource": ana.pk,
                "resource_from": luis.pk,
                "expect_start": "2026-10-29T17:00:00",
                "expect_end": "2026-10-29T18:00:00",
                "expect_resources": str(luis.pk),
            },
        )
        assert response.status_code == 200
        maria.refresh_from_db()
        assert (maria.professional, maria.start) == (ana, at(9))


class TestUndoingSeveral:
    def post(self, client, moves):
        return client.post(
            MOVES, json.dumps({"moves": moves}), content_type="application/json"
        )

    def test_none_when_one_changed_since(self, admin_client, maria, ana):
        other = Appointment.objects.create(
            client="Jorge", professional=ana, start=at(11), minutes=30
        )
        response = self.post(
            admin_client,
            [
                {
                    "pk": maria.pk,
                    "start": "2026-10-29T10:00:00",
                    "end": "",
                    "expect_start": "2026-10-29T09:00:00",
                    "expect_end": "2026-10-29T10:00:00",
                },
                {
                    "pk": other.pk,
                    "start": "2026-10-29T12:00:00",
                    "end": "",
                    "expect_start": "2026-10-29T13:00:00",  # It isn't there.
                },
            ],
        )
        assert response.status_code == 400
        assert response.json() == {
            "errors": {str(other.pk): "It was changed since, so this can't be undone."}
        }
        maria.refresh_from_db()
        assert maria.start == at(9)  # Not even the first one.

    def test_all_when_none_did(self, admin_client, maria, ana):
        other = Appointment.objects.create(
            client="Jorge", professional=ana, start=at(11), minutes=30
        )
        response = self.post(
            admin_client,
            [
                {
                    "pk": maria.pk,
                    "start": "2026-10-29T10:00:00",
                    "end": "",
                    "expect_start": "2026-10-29T09:00:00",
                    "expect_end": "2026-10-29T10:00:00",
                },
                {
                    "pk": other.pk,
                    "start": "2026-10-29T12:00:00",
                    "end": "",
                    "expect_start": "2026-10-29T11:00:00",
                    "expect_end": "2026-10-29T11:30:00",
                },
            ],
        )
        assert response.status_code == 200
        maria.refresh_from_db()
        other.refresh_from_db()
        assert (maria.start, other.start) == (at(10), at(12))
