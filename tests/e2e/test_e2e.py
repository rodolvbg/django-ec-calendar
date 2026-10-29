"""Real-browser end-to-end tests: the script and the endpoints are
unit-tested elsewhere (tests/js/, tests/test_admin.py); this file is about
them working together with EventCalendar itself, through an actual browser,
against a real running Django server.
"""

import datetime
import re

import pytest
from agenda.models import Appointment, Booking, Holiday, Professional, Room
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import Page, expect


class _AdminE2ETestCase(StaticLiveServerTestCase):
    """Shared setup for browser tests against the example admin: log in
    once per test, and bookings of this week (where the calendar opens).

    ``StaticLiveServerTestCase`` (a ``TransactionTestCase`` under the
    hood, with static files served too — needed since these tests load
    a real page that pulls in our JS) already runs each test in its own
    transaction the way ``@pytest.mark.django_db(transaction=True)``
    does, so that marker isn't needed here; it also gives
    ``self.live_server_url`` in place of the ``live_server`` fixture.
    pytest-playwright's ``page`` fixture still needs pytest's own
    injection, which doesn't reach unittest-style test methods as an
    extra parameter — so it's grabbed once per test via this autouse
    fixture instead, and stashed on ``self``.
    """

    @pytest.fixture(autouse=True)
    def _inject_page(self, page: Page) -> None:
        self.page = page
        # A move asks first: yes (a test that says no says so).
        self.dialogs: list[str] = []
        self.answer = True
        page.on("dialog", self._answer)

    def _answer(self, dialog) -> None:
        self.dialogs.append(dialog.message)
        if self.answer:
            dialog.accept()
        else:
            dialog.dismiss()

    def editable(self, model) -> None:
        """Its calendar's moves on, for this test."""
        from django.contrib import admin

        model_admin = admin.site._registry[model]
        model_admin.calendar_editable = True
        self.addCleanup(delattr, model_admin, "calendar_editable")

    def tearDown(self) -> None:
        # Close the page before the test database is flushed (after
        # tearDown): a request still in flight, or one the page makes later,
        # would otherwise reach the server once its data, or its database
        # connection, is gone, breaking this test or the next one.
        page = getattr(self, "page", None)
        if page is not None and not page.is_closed():
            # Its routes first (a CSP test adds some): none left mid-request.
            page.unroute_all(behavior="ignoreErrors")
            page.close()
        super().tearDown()

    def login(self) -> None:
        get_user_model().objects.create_superuser(
            "admin", "admin@example.com", "password"
        )
        self.page.goto(f"{self.live_server_url}/admin/login/")
        self.page.fill('input[name="username"]', "admin")
        self.page.fill('input[name="password"]', "password")
        self.page.click('input[type="submit"]')
        expect(self.page).to_have_url(f"{self.live_server_url}/admin/")

    def at(self, weekday: int, hour: int, minute: int = 0) -> datetime.datetime:
        """This week's ``weekday`` (Monday: 0), at that time (the site's)."""
        today = timezone.localdate()
        day = today - datetime.timedelta(days=today.weekday() - weekday)
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, minute))
        )

    def book(self, title: str, weekday: int, start: int, end: int) -> Booking:
        room, _ = Room.objects.get_or_create(name="Blue", color="#2563eb")
        return Booking.objects.create(
            title=title,
            room=room,
            start=self.at(weekday, start),
            end=self.at(weekday, end),
        )

    def open_calendar(self, model: str = "booking", view: str = "timeGridWeek") -> None:
        self.page.goto(f"{self.live_server_url}/admin/agenda/{model}/")
        self.page.locator('a[href$="/calendar/"]').click()
        expect(self.page.locator(".ec")).to_be_visible()
        if view == "timeGridWeek":
            # The week's view, Monday first (a weekend day may be today).
            self.page.locator(".ec-timeGridWeek, .ec-time-grid").first.wait_for()


class TestBookings(_AdminE2ETestCase):
    def test_shows_them_at_the_sites_time_and_opens_one(self):
        call = self.book("Client call", 1, 10, 12)
        self.login()
        self.open_calendar()
        event = self.page.locator(".ec-event", has_text="Client call")
        expect(event).to_contain_text("10:00")
        event.click()
        # With the calendar's URL, to come back to it.
        expect(self.page).to_have_url(
            re.compile(rf"/admin/agenda/booking/{call.pk}/change/\?_ec_calendar=")
        )

    def slot(self, label: str) -> dict[str, float]:
        """Where the time grid's ``label`` hour is ("9:00 AM")."""
        box = self.page.locator(
            ".ec-sidebar .ec-slot", has_text=label
        ).first.bounding_box()
        assert box is not None
        return box

    def day(self, index: int) -> dict[str, float]:
        """The time grid's column of the week's ``index`` day (Sunday: 0)."""
        box = self.page.locator(".ec-body .ec-day").nth(index).bounding_box()
        assert box is not None
        return box

    def test_drags_one_and_saves_it(self):
        call = self.book("Client call", 1, 10, 11)
        self.login()
        self.open_calendar()
        page = self.page
        event = page.locator(".ec-event", has_text="Client call")
        box = event.bounding_box()
        assert box is not None
        hour = self.slot("9:00 AM")["y"] - self.slot("8:00 AM")["y"]
        start = (box["x"] + box["width"] / 2, box["y"] + 5)
        # Two hours later, a day after.
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(start[0] + self.day(1)["width"], start[1] + 2 * hour, steps=15)
        page.mouse.up()
        expect(event).to_contain_text("12:00")
        expect(page.locator(".django-ec-calendar-status")).to_be_hidden()
        page.wait_for_timeout(300)
        call.refresh_from_db()
        assert (call.start, call.end) == (self.at(2, 12), self.at(2, 13))
        # Wednesday (Sunday is the first column).
        assert self.day(3)["x"] <= event.bounding_box()["x"] < self.day(4)["x"]

    def test_resizes_one_and_saves_it(self):
        call = self.book("Client call", 1, 10, 11)
        self.login()
        self.open_calendar()
        page = self.page
        event = page.locator(".ec-event", has_text="Client call")
        event.hover()
        resizer = event.locator(".ec-resizer").last.bounding_box()
        assert resizer is not None
        hour = self.slot("9:00 AM")["y"] - self.slot("8:00 AM")["y"]
        x, y = resizer["x"] + resizer["width"] / 2, resizer["y"] + resizer["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x, y + hour, steps=10)
        page.mouse.up()
        expect(event).to_contain_text("12:00")
        page.wait_for_timeout(300)
        call.refresh_from_db()
        assert (call.start, call.end) == (self.at(1, 10), self.at(1, 12))

    def test_a_move_refused_goes_back(self):
        call = self.book("Client call", 1, 10, 11)
        self.login()
        self.open_calendar()
        page = self.page
        # As the model's clean() refuses one.
        page.route(
            "**/calendar/move/",
            lambda route: route.fulfill(
                status=400,
                content_type="application/json",
                body='{"error": "It can\'t end before it starts."}',
            ),
        )
        event = page.locator(".ec-event").first
        box = event.bounding_box()
        assert box is not None
        hour = self.slot("9:00 AM")["y"] - self.slot("8:00 AM")["y"]
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 5)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 5 + hour, steps=10)
        page.mouse.up()
        status = page.locator(".django-ec-calendar-status")
        expect(status).to_be_visible()
        expect(status).to_have_text("It can't end before it starts.")
        expect(event).to_contain_text("10:00")
        call.refresh_from_db()
        assert call.start == self.at(1, 10)

    def test_selects_dates_to_add_one(self):
        self.login()
        self.open_calendar()
        page = self.page
        # Monday, from 9:00 to 11:00: dragged over its slots.
        x = self.day(1)["x"] + self.day(1)["width"] / 2
        hour = self.slot("9:00 AM")["y"] - self.slot("8:00 AM")["y"]
        # The column starts at 7:00 (slotMinTime): from 9:15 to 10:45, in
        # half-hour slots 9:00 to 11:00.
        seven = self.day(1)["y"]
        page.mouse.move(x, seven + hour * 2.25)
        page.mouse.down()
        page.mouse.move(x, seven + hour * 3.75, steps=10)
        page.mouse.up()
        expect(page).to_have_url(re.compile(r"/admin/agenda/booking/add/\?start="))
        assert page.locator("#id_start_1").input_value().startswith("09:00")
        assert page.locator("#id_end_1").input_value().startswith("11:00")

    def test_a_click_adds_one_at_its_slot(self):
        self.login()
        self.open_calendar()
        page = self.page
        x = self.day(1)["x"] + self.day(1)["width"] / 2
        hour = self.slot("9:00 AM")["y"] - self.slot("8:00 AM")["y"]
        # 9:20, in the 9:00 slot (of half an hour): the slot's start.
        page.mouse.click(x, self.day(1)["y"] + hour * (2 + 20 / 60))
        expect(page).to_have_url(re.compile(r"/admin/agenda/booking/add/\?start="))
        assert page.locator("#id_start_1").input_value().startswith("09:00")

    def test_its_events_let_a_page_do_otherwise(self):
        call = self.book("Client call", 1, 10, 12)
        self.login()
        self.open_calendar()
        page = self.page
        # A page of its own: a click on an event opens its dialog instead.
        page.evaluate(
            """() => document.addEventListener(
                "django-ec-calendar:event-click",
                (event) => {
                    event.preventDefault();
                    document.title = `Open ${event.detail.event.id}`;
                },
            )"""
        )
        page.locator(".ec-event", has_text="Client call").click()
        expect(page).to_have_title(f"Open {call.pk}")
        assert "/calendar/?" in page.url  # Still on it.

    def test_in_another_time_zone_the_same_times(self):
        self.book("Client call", 1, 10, 12)
        self.page.close()
        context = self.page.context.browser.new_context(timezone_id="Pacific/Auckland")
        self.page = context.new_page()
        self.login()
        self.open_calendar()
        event = self.page.locator(".ec-event", has_text="Client call")
        expect(event).to_contain_text("10:00")

    def test_under_a_strict_content_security_policy(self):
        self.book("Client call", 1, 10, 12)
        self.login()
        page = self.page
        violations: list[str] = []
        page.on(
            "console",
            lambda message: (
                "Content Security Policy" in message.text
                and violations.append(message.text)
            ),
        )

        def strict(route):
            response = route.fetch()
            route.fulfill(
                response=response,
                headers={
                    **response.headers,
                    "content-security-policy": (
                        "default-src 'self'; script-src 'self'; style-src 'self'"
                    ),
                },
            )

        page.route("**/calendar/", strict)
        self.open_calendar()
        event = page.locator(".ec-event", has_text="Client call")
        expect(event).to_contain_text("10:00")
        assert event.evaluate("e => getComputedStyle(e).backgroundColor") == (
            "rgb(37, 99, 235)"  # Its room's color: a style EventCalendar sets.
        )
        assert violations == []


class TestHolidays(_AdminE2ETestCase):
    def test_whole_days_dragged(self):
        # A Tuesday of this month's second week: its row has room after it.
        first = timezone.localdate().replace(day=8)
        first += datetime.timedelta(days=(1 - first.weekday()) % 7)
        holiday = Holiday.objects.create(
            name="Retreat", first_day=first, last_day=first + datetime.timedelta(days=1)
        )
        self.editable(Holiday)
        self.login()
        self.open_calendar("holiday", "dayGridMonth")
        page = self.page
        event = page.locator(".ec-event", has_text="Retreat")
        box = event.bounding_box()
        assert box is not None
        day = page.locator(".ec-day").first.bounding_box()
        assert day is not None
        page.mouse.move(box["x"] + 10, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(
            box["x"] + 10 + day["width"], box["y"] + box["height"] / 2, steps=10
        )
        page.mouse.up()
        page.wait_for_timeout(500)
        holiday.refresh_from_db()
        assert holiday.first_day == first + datetime.timedelta(days=1)
        assert holiday.last_day == first + datetime.timedelta(days=2)


class TestAppointments(_AdminE2ETestCase):
    """A column per professional (resourceTimeGridDay), today."""

    def setUp(self) -> None:
        super().setUp()
        from django.contrib import admin

        # Open always, whatever day the tests run (TestHours has its own).
        model_admin = admin.site._registry[Appointment]
        self.hours: list[dict] | None = None
        model_admin.get_calendar_business_hours = lambda request, resource=None: (
            self.hours
        )
        model_admin.get_calendar_closed = lambda *args, **kwargs: ()
        # Its morning in sight.
        model_admin.calendar_options = {"slotMinTime": "08:00", "slotMaxTime": "20:00"}
        for name in (
            "get_calendar_business_hours",
            "get_calendar_closed",
            "calendar_options",
        ):
            self.addCleanup(delattr, model_admin, name)
        self.ana = Professional.objects.create(name="Ana")
        self.luis = Professional.objects.create(name="Luis")
        start = timezone.make_aware(
            datetime.datetime.combine(timezone.localdate(), datetime.time(9))
        )
        self.maria = Appointment.objects.create(
            client="María",
            professional=self.ana,
            start=start,
            minutes=60,
            status="confirmed",
        )

    def open(self) -> None:
        self.login()
        self.page.goto(f"{self.live_server_url}/admin/agenda/appointment/calendar/")
        expect(self.page.locator(".ec-event", has_text="María")).to_be_visible()

    def column(self, name: str) -> dict[str, float]:
        box = self.page.locator(
            ".ec-header .ec-col-head", has_text=name
        ).first.bounding_box()
        assert box is not None
        return box

    def drag_to(self, name: str) -> None:
        page = self.page
        box = page.locator(".ec-event", has_text="María").bounding_box()
        assert box is not None
        column = self.column(name)
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 5)
        page.mouse.down()
        page.mouse.move(column["x"] + column["width"] / 2, box["y"] + 5, steps=15)
        page.mouse.up()

    def test_its_details_and_no_tint_in_a_day(self):
        self.open()
        expect(self.page.locator(".ec-event", has_text="María")).to_contain_text(
            "Confirmed"
        )
        tint = self.page.locator(".ec").evaluate(
            "e => getComputedStyle(e).getPropertyValue('--ec-today-bg-color').trim()"
        )
        assert tint == "transparent"

    def test_dragged_to_another_professional(self):
        self.open()
        self.drag_to("Luis")
        expect(self.page.locator(".django-ec-calendar-status")).to_be_hidden()
        self.page.wait_for_timeout(400)
        assert self.dialogs == ["Save the new dates of “María”?"]
        self.maria.refresh_from_db()
        assert self.maria.professional == self.luis
        event = self.page.locator(".ec-event", has_text="María").bounding_box()
        luis = self.column("Luis")
        assert event and luis["x"] <= event["x"] < luis["x"] + luis["width"]

    def test_a_move_one_says_no_to_goes_back(self):
        self.answer = False
        self.open()
        self.drag_to("Luis")
        self.page.wait_for_timeout(400)
        assert len(self.dialogs) == 1
        self.maria.refresh_from_db()
        assert self.maria.professional == self.ana
        event = self.page.locator(".ec-event", has_text="María").bounding_box()
        ana = self.column("Ana")
        assert event and ana["x"] <= event["x"] < ana["x"] + ana["width"]

    def test_back_where_it_was_after_a_save(self):
        self.open()
        page = self.page
        page.locator(".ec-toolbar button", has_text="List").click()
        expect(page).to_have_url(re.compile(r"ec-view=listWeek"))
        page.locator(".ec-event", has_text="María").click()
        expect(page).to_have_url(re.compile(r"/change/\?_ec_calendar="))
        page.locator("input[name=_save]").click()
        expect(page).to_have_url(
            re.compile(r"/appointment/calendar/\?.*ec-view=listWeek")
        )
        expect(page.locator(".ec-list")).to_be_visible()

    def test_its_filters_keep_its_place(self):
        self.open()
        page = self.page
        page.locator(".ec-toolbar button", has_text="Week").click()
        expect(page).to_have_url(re.compile(r"ec-view=resourceTimeGridWeek"))
        page.locator("#changelist-filter a", has_text="Luis").click()
        expect(page).to_have_url(re.compile(r"professional__id__exact="))
        assert "ec-view=resourceTimeGridWeek" in page.url
        header = page.locator(".ec-header").first
        expect(header).to_contain_text("Luis")
        assert "Ana" not in header.inner_text()


class TestHours(TestAppointments):
    """Open from midnight to noon, every day: blocked out of it."""

    def setUp(self) -> None:
        super().setUp()
        self.hours = [{"start": "00:00", "end": "12:00"}]

    def test_shaded_and_not_moved_out_of_them(self):
        self.open()
        page = self.page
        expect(
            page.locator(".ec-bg-event.django-ec-calendar-closed").first
        ).to_be_attached()
        event = page.locator(".ec-event", has_text="María")
        box = event.bounding_box()
        assert box is not None
        hour = box["height"]  # An hour (9 to 10).
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 5)
        page.mouse.down()
        # To 14:00: closed. It stays (where it was allowed).
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 5 + 5 * hour, steps=20)
        page.mouse.up()
        page.wait_for_timeout(400)
        self.maria.refresh_from_db()
        assert self.maria.start.astimezone(timezone.get_current_timezone()).hour < 12

    # Its other tests, with hours: the same.
    test_its_details_and_no_tint_in_a_day = None
    test_a_move_one_says_no_to_goes_back = None
    test_back_where_it_was_after_a_save = None
    test_its_filters_keep_its_place = None
    test_dragged_to_another_professional = None


class TestPage(_AdminE2ETestCase):
    def test_a_calendar_on_a_page(self):
        call = self.book("Client call", 1, 10, 12)
        self.page.goto(f"{self.live_server_url}/")
        event = self.page.locator(".ec-event", has_text="Client call")
        expect(event).to_contain_text("10:00")
        event.click()
        expect(self.page).to_have_url(f"{self.live_server_url}/bookings/{call.pk}/")
