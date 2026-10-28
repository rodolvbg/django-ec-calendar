"""The calendar's configuration, for its script, and what it loads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.forms import Media
from django.middleware.csrf import get_token
from django.utils import formats, timezone
from django.utils.translation import get_language, gettext

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django.http import HttpRequest

#: The vendored EventCalendar 5.17.1 (its standalone build, as published).
VENDOR = "django_event_calendar/vendor/event-calendar"


def calendar_media() -> Media:
    """EventCalendar's script and stylesheet, and the package's."""
    return Media(
        css={
            "all": [
                f"{VENDOR}/event-calendar.min.css",
                "django_event_calendar/calendar.css",
            ]
        },
        js=[f"{VENDOR}/event-calendar.min.js", "django_event_calendar/calendar.js"],
    )


def calendar_texts() -> dict[str, str]:
    """Its words, in the request's language (the days' and months' names
    come from the browser's, in ``locale``)."""
    return {
        "today": gettext("Today"),
        "dayGridMonth": gettext("Month"),
        "dayGridWeek": gettext("Week"),
        "dayGridDay": gettext("Day"),
        "timeGridWeek": gettext("Week"),
        "timeGridDay": gettext("Day"),
        "listDay": gettext("List"),
        "listWeek": gettext("List"),
        "listMonth": gettext("List"),
        "listYear": gettext("List"),
        "allDay": gettext("All day"),
        "noEvents": gettext("No events"),
        # %(count)s: how many more there are that day.
        "more": gettext("+%(count)s more"),
        "close": gettext("Close"),
        "saving": gettext("Saving…"),
        "failed": gettext("Not saved"),
    }


def site_time_zone() -> str:
    """The calendar's ``timeZone``: the current time zone's offset now
    (``"+01:00"``), for "today" and the time now; without time zones, the
    browser's (``"local"``). The events' times show as they are, either way."""
    if not timezone.is_aware(timezone.now()):
        return "local"
    offset = timezone.localtime().strftime("%z")
    return f"{offset[:3]}:{offset[3:]}"


def calendar_config(
    request: HttpRequest,
    *,
    events: str,
    params: Mapping[str, str] | None = None,
    view: str = "dayGridMonth",
    views: Sequence[str] = (),
    add: str | None = None,
    move: str | None = None,
    dates_only: bool = False,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """What ``calendar.js`` reads: where the events are (``events``, with
    ``params`` too), the views, where selecting dates leads (``add``) and
    where a move is saved (``move``); none of them: not offered."""
    language = get_language() or "en"
    return {
        "events": events,
        "params": dict(params or {}),
        "view": view,
        "views": list(views),
        "add": add,
        "move": move,
        "csrfToken": get_token(request) if move else "",
        "datesOnly": dates_only,
        "locale": language,
        "firstDay": int(formats.get_format("FIRST_DAY_OF_WEEK")),
        "timeZone": site_time_zone(),
        "texts": calendar_texts(),
        "options": dict(options or {}),
    }
