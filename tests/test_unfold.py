"""django_ec_calendar.unfold: the sidebar's items of a list and its calendar."""

import pytest
from django.contrib.auth.models import Permission, User
from django.test import RequestFactory

from django_ec_calendar.unfold import (
    calendar_item,
    calendar_navigation,
    changelist_item,
)

LIST = "/admin/agenda/booking/"
CALENDAR = "/admin/agenda/booking/calendar/"


def request(path, user=None):
    made = RequestFactory().get(path)
    made.user = user
    return made


@pytest.mark.parametrize(
    ("path", "on_list", "on_calendar"),
    [
        (LIST, True, False),
        (f"{LIST}3/change/", True, False),
        (CALENDAR, False, True),
        (f"{CALENDAR}?ec-view=listWeek", False, True),
        ("/admin/agenda/holiday/", False, False),
    ],
)
def test_each_active_on_its_own_pages(path, on_list, on_calendar):
    list_item, calendar = calendar_navigation("agenda.Booking")
    assert list_item["active"](request(path)) is on_list
    assert calendar["active"](request(path)) is on_calendar


def test_their_links_titles_and_icons():
    list_item, calendar = calendar_navigation(
        "agenda.Booking", calendar_title="Bookings' calendar"
    )
    assert str(list_item["link"]) == LIST
    assert str(list_item["title"]) == "Bookings"
    assert list_item["icon"] == "list"
    assert str(calendar["link"]) == CALENDAR
    assert str(calendar["title"]) == "Bookings' calendar"
    assert calendar["icon"] == "calendar_month"
    assert str(calendar_item("agenda.Booking")["title"]) == "Calendar"
    assert str(changelist_item("agenda.Booking", title="All")["title"]) == "All"


def test_for_who_may_view_or_change(db):
    clerk = User.objects.create_user("clerk")
    allowed = calendar_item("agenda.Booking")["permission"]
    assert allowed(request(CALENDAR, clerk)) is False
    clerk.user_permissions.add(Permission.objects.get(codename="change_booking"))
    clerk = User.objects.get(pk=clerk.pk)
    assert allowed(request(CALENDAR, clerk)) is True
