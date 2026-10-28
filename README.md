# django-event-calendar

[![Python tests](https://github.com/rodolvbg/django-event-calendar/actions/workflows/pytest.yml/badge.svg)](https://github.com/rodolvbg/django-event-calendar/actions/workflows/pytest.yml)
[![JavaScript tests](https://github.com/rodolvbg/django-event-calendar/actions/workflows/js-tests.yml/badge.svg)](https://github.com/rodolvbg/django-event-calendar/actions/workflows/js-tests.yml)
[![Current version on PyPI](https://img.shields.io/pypi/v/django-event-calendar.svg)](https://pypi.org/project/django-event-calendar/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-event-calendar)](https://pypi.org/project/django-event-calendar/)
[![PyPI - Django Version](https://img.shields.io/pypi/djversions/django-event-calendar)](https://pypi.org/project/django-event-calendar/)
[![Downloads](https://static.pepy.tech/personalized-badge/django-event-calendar?period=month&units=international_system&left_color=black&right_color=blue&left_text=Downloads/month)](https://pepy.tech/project/django-event-calendar)

A calendar for the Django admin and your own pages, with
[EventCalendar](https://github.com/vkurko/calendar) (by vkurko, MIT): a
changelist's objects by date — opened with a click, added by selecting the
dates, moved and resized by dragging — in Django's admin and in
[django-unfold](https://github.com/unfoldadmin/django-unfold), light and
dark.

![The bookings of a week in the admin's calendar, each in its room's color](docs/screenshots/calendar.png)

## Install

```bash
uv add django-event-calendar
# or
pip install django-event-calendar
```

Add it to `INSTALLED_APPS` (so Django finds its templates, and
`django.contrib.staticfiles` its JS and CSS — EventCalendar included, no
CDN):

```python
INSTALLED_APPS = [
    ...,
    "django_event_calendar",
]
```

## In the admin

```python
from django.contrib import admin
from django_event_calendar import CalendarAdminMixin


@admin.register(Booking)
class BookingAdmin(CalendarAdminMixin, admin.ModelAdmin):
    list_filter = ("room",)
    search_fields = ("title",)
    calendar_start_field = "start"
    calendar_end_field = "end"  # optional
    calendar_color_field = "color"  # optional: a CSS color, a field or property
    calendar_view = "timeGridWeek"  # optional ("dayGridMonth")
    calendar_options = {"slotMinTime": "07:00"}  # optional: any of EventCalendar's
```

The changelist gets a "Calendar" link, next to "Add":

- **What it shows** is what the changelist would: its `get_queryset()`, and
  the filters and search it had when the link was followed. One query per
  range the calendar shows.
- **A click** on an event opens its change page (read-only, for those who
  may only view it).
- **Selecting dates** (or clicking one) opens the add page with them, for
  those who may add (`calendar_selectable = False`: not). A click starts
  at its slot's start (9:20 in half-hour slots: 9:00).
- **Dragging** an event, or its end, saves its dates, for those who may
  change it (`calendar_editable = False`: not). The move is checked by the
  model (`full_clean()` of its dates, and its `clean()`), saved through
  `save_model()` and logged as the admin's changes are; what can't be
  saved goes back, saying why.
- **Its views**: `calendar_views` — by default month, week, day and list
  (`dayGridMonth`, `timeGridWeek`, `timeGridDay`, `listMonth`; any of
  [EventCalendar's](https://github.com/vkurko/calendar#view)).

### In the menu

The calendar's URL is `admin:<app>_<model>_calendar`; in Unfold's sidebar,
for instance:

```python
UNFOLD = {
    "SIDEBAR": {
        "navigation": [
            {
                "title": "Agenda",
                "items": [
                    {
                        "title": "Calendar",
                        "icon": "calendar_month",
                        "link": reverse_lazy("admin:agenda_booking_calendar"),
                    },
                ],
            },
        ],
    },
}
```

### Its fields

| Option | |
|---|---|
| `calendar_start_field` | A `DateTimeField` (events at a time) or a `DateField` (all-day events). Required. |
| `calendar_end_field` | Where it ends (none: it lasts no time, or its day; it can't be resized). |
| `calendar_all_day_field` | A `BooleanField`: true, an all-day event of a `DateTimeField`. |
| `calendar_title_field` | Its title (none: `str(obj)`). |
| `calendar_color_field` | Its color, a CSS color (none: the admin's). |

`get_calendar_event(request, obj)` makes the whole event (any of
[EventCalendar's event](https://github.com/vkurko/calendar#event-object)
properties), calling `super()`.

A `DateField`'s end is the last day (EventCalendar's is the day after: it's
converted both ways).

![Whole days: a month of holidays](docs/screenshots/calendar-days.png)

### Time zones

Times show as the wall-clock time of Django's current time zone, and are
saved so, whatever the browser's: an event at 10:00 in Madrid shows at
10:00 to someone in New York too. "Today" and the time now are the site's.

### Unfold, dark

With Unfold, in its colors, and next to its buttons. In both, the calendar
follows the page's theme, light or dark (the admin's theme switch,
Unfold's), else the system's.

![The same week in Unfold](docs/screenshots/calendar-unfold.png)

![In the admin's dark theme](docs/screenshots/calendar-dark.png)

![In Unfold's dark theme](docs/screenshots/calendar-unfold-dark.png)

## On your pages

A view with the events, as the calendar asks for them:

```python
from django_event_calendar import EventFeedView


class BookingEvents(EventFeedView):
    queryset = Booking.objects.select_related("room")  # or model, get_queryset()
    calendar_start_field = "start"
    calendar_end_field = "end"
    calendar_color_field = "color"
```

```python
urlpatterns = [path("events/", BookingEvents.as_view(), name="booking-events")]
```

Each event leads to the object's `get_absolute_url()` (override
`get_calendar_event_url(obj)`). Who may see them is the view's own
business: `LoginRequiredMixin`, `get_queryset()`…

And the calendar, in a template:

```django
{% load event_calendar %}
<head>
  ...
  {% event_calendar_media %}
</head>
<body>
  {% url "booking-events" as events %}
  {% event_calendar events view="timeGridWeek" views="dayGridMonth timeGridWeek listWeek" slotMinTime="07:00" %}
</body>
```

`views` are separated by spaces (empty: none to switch to); any other
keyword is one of EventCalendar's options. On a page it's read-only.

![A calendar on a page](docs/screenshots/calendar-page.png)

### Its events, for doing otherwise

Before it does what it does, the calendar fires an event on its element,
which bubbles and can be cancelled — `preventDefault()`, and it isn't done
— with the dates as the server reads them:

| Event | `detail` | Otherwise |
|---|---|---|
| `django-event-calendar:event-click` | `event` (EventCalendar's), `url`, `jsEvent` | Opens `url`. |
| `django-event-calendar:date-click` | `start`, `allDay`, `jsEvent` | Opens the add page. |
| `django-event-calendar:select` | `start`, `end`, `allDay`, `jsEvent` | Opens the add page. |
| `django-event-calendar:event-change` | `event`, `saved`, `error` | (After a move; not cancellable.) |

```js
document.addEventListener("django-event-calendar:event-click", (event) => {
    event.preventDefault();
    openDialog(event.detail.url);  // A dialog, instead of a page.
});
```

They fire without an add page too (on your pages, `selectable: true` in the
options for selections).

The script makes every `[data-django-event-calendar]` on the page;
`window.djangoEventCalendar.setup()` makes those added later, and
`window.djangoEventCalendar.go` is where a click leads (a single-page app's
router, instead of a page load).

## Content Security Policy

It works under a strict policy (`script-src 'self'; style-src 'self'`, no
`'unsafe-inline'`): each calendar's configuration is a JSON data block
(`json_script`, which `script-src` doesn't run), read by the package's own
script, and EventCalendar sets its elements' styles through the CSSOM
(which `style-src` doesn't restrict).

## Translations

Ships a Spanish (`es`) translation; the days' and months' names come from
the browser, in the request's language, and the first day of the week from
Django's `FIRST_DAY_OF_WEEK`.

## EventCalendar

[EventCalendar](https://github.com/vkurko/calendar) 5.17.1's standalone
build is included as it's published
(`static/django_event_calendar/vendor/event-calendar/`, with its MIT
license). Its options are documented in
[its README](https://github.com/vkurko/calendar#options).

## Supported versions

Django 4.2 – 6.1, Python 3.10+.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, running the example
project, and the test/lint/type-check commands.
