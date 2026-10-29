"""How dragging goes (calendar_move_mode), and several moves saved together."""

import datetime
import json
import zoneinfo

import pytest
from agenda.models import Appointment, Booking, Professional, Room
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.core.exceptions import ImproperlyConfigured

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
APPOINTMENTS = "/admin/agenda/appointment/"
MOVES = f"{APPOINTMENTS}calendar/moves/"
BOOKINGS = "/admin/agenda/booking/"


def at(hour, minute=0):
    return datetime.datetime(2026, 10, 29, hour, minute, tzinfo=MADRID)


def post(client, moves, url=MOVES):
    return client.post(
        url, json.dumps({"moves": moves}), content_type="application/json"
    )


@pytest.fixture
def ana(db):
    return Professional.objects.create(name="Ana")  # 9 to 14 (the example's).


@pytest.fixture
def luis(db):
    return Professional.objects.create(name="Luis")  # 16 to 20.


@pytest.fixture
def maria(ana):
    return Appointment.objects.create(
        client="María", professional=ana, start=at(9), minutes=60
    )


@pytest.fixture
def jorge(ana):
    return Appointment.objects.create(
        client="Jorge", professional=ana, start=at(11), minutes=30
    )


class TestMode:
    def test_in_the_configuration(self, admin_client):
        html = admin_client.get(f"{APPOINTMENTS}calendar/").content.decode()
        assert '"moveMode": "batch"' in html
        assert f'"moves": "{MOVES}"' in html

    def test_off_nothing_to_move(self, admin_client, monkeypatch, maria):
        model_admin = admin.site._registry[Appointment]
        monkeypatch.setattr(model_admin, "calendar_move_mode", "off")
        html = admin_client.get(f"{APPOINTMENTS}calendar/").content.decode()
        assert '"moveMode": "off"' in html
        assert '"move": null' in html
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/",
            {"pk": maria.pk, "start": "2026-10-29T10:00:00"},
        )
        assert response.status_code == 403

    def test_only_one_it_knows(self, monkeypatch, rf):
        model_admin = admin.site._registry[Appointment]
        monkeypatch.setattr(model_admin, "calendar_move_mode", "drag")
        with pytest.raises(ImproperlyConfigured, match="is one of off, save, confirm"):
            model_admin.get_calendar_move_mode(rf.get("/"))

    def test_off_for_who_may_only_view(self, client, db):
        from django.contrib.auth.models import Permission, User

        clerk = User.objects.create_user("clerk", is_staff=True)
        clerk.user_permissions.add(Permission.objects.get(codename="view_appointment"))
        client.force_login(clerk)
        html = client.get(f"{APPOINTMENTS}calendar/").content.decode()
        assert '"moveMode": "off"' in html
        assert '"moves": null' in html


class TestSeveralTogether:
    def test_all_saved_and_logged(self, admin_client, maria, jorge, luis):
        response = post(
            admin_client,
            [
                {
                    "pk": maria.pk,
                    "start": "2026-10-29T10:00:00",
                    "end": "2026-10-29T10:30:00",
                },
                {
                    "pk": jorge.pk,
                    "start": "2026-10-29T17:00:00",
                    "end": "2026-10-29T17:30:00",
                    "resource": luis.pk,
                    "resource_from": jorge.professional_id,
                },
            ],
        )
        assert response.status_code == 200
        assert [event["title"] for event in response.json()["events"]] == [
            "María",
            "Jorge",
        ]
        maria.refresh_from_db()
        jorge.refresh_from_db()
        assert (maria.start, maria.minutes) == (at(10), 30)
        assert (jorge.start, jorge.professional) == (at(17), luis)
        assert LogEntry.objects.count() == 2

    def test_none_when_any_cant_be(self, admin_client, maria, jorge):
        response = post(
            admin_client,
            [
                {"pk": maria.pk, "start": "2026-10-29T10:00:00", "end": ""},
                {"pk": jorge.pk, "start": "2026-10-29T15:00:00", "end": ""},  # Closed.
                {"pk": 999, "start": "2026-10-29T10:00:00"},
            ],
        )
        assert response.status_code == 400
        assert response.json() == {
            "errors": {
                str(jorge.pk): "It's out of the business hours.",
                "999": "It doesn't exist any more.",
            }
        }
        maria.refresh_from_db()
        assert maria.start == at(9)  # Not saved either.
        assert not LogEntry.objects.exists()

    def test_in_a_transaction(self, admin_client, maria, jorge, monkeypatch):
        model_admin = admin.site._registry[Appointment]
        saved = model_admin.save_calendar_move

        def second_fails(request, move):
            if move.obj.pk == jorge.pk:
                raise RuntimeError("the database is gone")
            saved(request, move)

        monkeypatch.setattr(model_admin, "save_calendar_move", second_fails)
        with pytest.raises(RuntimeError):
            post(
                admin_client,
                [
                    {"pk": maria.pk, "start": "2026-10-29T10:00:00", "end": ""},
                    {"pk": jorge.pk, "start": "2026-10-29T12:00:00", "end": ""},
                ],
            )
        maria.refresh_from_db()
        assert maria.start == at(9)  # Rolled back.

    def test_who_may_not_move_one(self, admin_client, maria, monkeypatch):
        model_admin = admin.site._registry[Appointment]
        monkeypatch.setattr(
            model_admin,
            "has_calendar_move_permission",
            lambda request, obj=None: obj is None,
        )
        response = post(
            admin_client, [{"pk": maria.pk, "start": "2026-10-29T10:00:00"}]
        )
        assert response.json() == {"errors": {str(maria.pk): "You may not move it."}}

    @pytest.mark.parametrize(
        "body",
        ["", "[]", '{"moves": 3}', '{"moves": [3]}', "not json", '{"other": []}'],
    )
    def test_not_a_list_of_moves(self, admin_client, db, body):
        response = admin_client.post(MOVES, body, content_type="application/json")
        assert response.status_code == 400
        assert response.json() == {"error": "Not a list of moves."}

    def test_only_in_batch_mode(self, admin_client, db):
        room = Room.objects.create(name="Blue")
        Booking.objects.create(title="x", room=room, start=at(9), end=at(10))
        response = post(admin_client, [], url=f"{BOOKINGS}calendar/moves/")
        assert response.status_code == 403  # "confirm".

    def test_an_unknown_filter(self, admin_client, db, monkeypatch):
        from django.contrib.admin.options import IncorrectLookupParameters

        model_admin = admin.site._registry[Appointment]

        def unknown(request):
            raise IncorrectLookupParameters

        monkeypatch.setattr(model_admin, "get_calendar_queryset", unknown)
        assert post(admin_client, []).status_code == 400
        response = admin_client.post(
            f"{APPOINTMENTS}calendar/move/", {"pk": 1, "start": "2026-10-29T10:00:00"}
        )
        assert response.status_code == 404


def test_a_move_its_resource_given_as_a_number(admin_client, maria, luis):
    # (A JSON body has numbers: as the form's strings.)
    response = post(
        admin_client,
        [
            {
                "pk": maria.pk,
                "start": "2026-10-29T17:00:00",
                "end": "",
                "resource": luis.pk,
                "resource_from": None,
            }
        ],
    )
    assert response.status_code == 200
    maria.refresh_from_db()
    assert maria.professional == luis
