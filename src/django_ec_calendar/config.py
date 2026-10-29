"""The calendar's configuration, for its script, and what it loads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from django.forms import Media
from django.middleware.csrf import get_token
from django.utils import formats, timezone
from django.utils.translation import get_language, gettext, ngettext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.http import HttpRequest

#: The vendored EventCalendar 5.17.1 (its standalone build, as published).
VENDOR = "django_ec_calendar/vendor/event-calendar"


def calendar_media() -> Media:
    """EventCalendar's script and stylesheet, and the package's."""
    return Media(
        css={
            "all": [
                f"{VENDOR}/event-calendar.min.css",
                "django_ec_calendar/calendar.css",
            ]
        },
        js=[f"{VENDOR}/event-calendar.min.js", "django_ec_calendar/calendar.js"],
    )


def calendar_texts() -> dict[str, Any]:
    """Its words, in the request's language (the days' and months' names
    come from the browser's, in ``locale``): its buttons' (``buttons``),
    EventCalendar's own others by their English (``labels``: its views'
    "prev" and "next"), and the package's."""
    day, week, month, year = (
        gettext("Day"),
        gettext("Week"),
        gettext("Month"),
        gettext("Year"),
    )
    listed = gettext("List")
    return {
        "buttons": {
            "today": gettext("Today"),
            "close": gettext("Close"),
            "expand": gettext("Expand"),
            "collapse": gettext("Collapse"),
            "dayGridDay": day,
            "dayGridWeek": week,
            "dayGridMonth": month,
            "timeGridDay": day,
            "timeGridWeek": week,
            "listDay": listed,
            "listWeek": listed,
            "listMonth": listed,
            "listYear": listed,
            "resourceTimeGridDay": day,
            "resourceTimeGridWeek": week,
            "resourceTimelineDay": day,
            "resourceTimelineWeek": week,
            "resourceTimelineMonth": month,
            "resourceTimelineYear": year,
        },
        "labels": {
            "Previous day": gettext("Previous day"),
            "Next day": gettext("Next day"),
            "Previous week": gettext("Previous week"),
            "Next week": gettext("Next week"),
            "Previous month": gettext("Previous month"),
            "Next month": gettext("Next month"),
            "Previous year": gettext("Previous year"),
            "Next year": gettext("Next year"),
        },
        "allDay": gettext("All day"),
        "noEvents": gettext("No events"),
        # %(count)s: how many more there are that day.
        "more": gettext("+%(count)s more"),
        "goToDate": gettext("Go to a date"),
        "saving": gettext("Saving…"),
        "save": gettext("Save"),
        "discard": gettext("Discard"),
        # How many moves wait to be saved (calendar_move_mode "batch").
        "pending": {
            "one": ngettext(
                "%(count)s change not saved", "%(count)s changes not saved", 1
            ),
            "other": ngettext(
                "%(count)s change not saved", "%(count)s changes not saved", 2
            ),
        },
        "failed": gettext("Not saved"),
        # %(title)s: the event's.
        "confirmMove": gettext("Save the new dates of “%(title)s”?"),
    }


def site_time_zone() -> str:
    """The calendar's ``timeZone``: the current time zone's offset now
    (``"+01:00"``), for "today" and the time now; without time zones, the
    browser's (``"local"``). The events' times show as they are, either way."""
    if not timezone.is_aware(timezone.now()):
        return "local"
    offset = timezone.localtime().strftime("%z")
    return f"{offset[:3]}:{offset[3:]}"


def _resources(
    resources: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> list[dict[str, Any]] | dict[str, Any] | None:
    if resources is None:
        return None
    if isinstance(resources, Mapping):
        return dict(resources)
    return [dict(item) for item in resources]


def calendar_config(
    request: HttpRequest,
    *,
    events: str,
    params: Mapping[str, str] | None = None,
    view: str = "dayGridMonth",
    views: Sequence[str] = (),
    add: str | None = None,
    move: str | None = None,
    moves: str | None = None,
    move_mode: str = "off",
    dates_only: bool = False,
    resources: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    resource: Mapping[str, Any] | None = None,
    url_state: bool = True,
    url_params: Mapping[str, str] | None = None,
    url_views: Mapping[str, str] | None = None,
    highlight_today: bool = True,
    date_picker: bool = False,
    outside_hours: str = "shade",
    return_param: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """What ``calendar.js`` reads: where the events are (``events``, with
    ``params`` too), the views, where selecting dates leads (``add``) and
    where a move is saved (``move``; none of them: not offered).

    ``resources``, EventCalendar's: a list, or ``{url}`` to fetch it (none:
    no resource views); ``resource``, how an event's is sent (``{param,
    empty, editable, message}``: its field's name, the id of none, whether
    a move may change it, and what it says when it may not). ``url_state``:
    whether the view and its date go in the page's URL (``ec-view``,
    ``ec-date``, or ``url_params``' names; the views by ``url_views``'), and
    are read from it.
    ``highlight_today``: whether today is tinted (never in a day's view).
    ``date_picker``: whether its toolbar has a date field, to go to one.
    ``move_mode``: how a drag goes (``"off"``, ``"save"``, ``"confirm"``,
    ``"batch"``: kept, and saved together at ``moves``). ``outside_hours``: out of the
    business hours (its background events), ``"shade"`` or ``"block"`` (not
    to be selected, nor moved to). ``return_param``: the
    parameter that takes the calendar's URL to the pages it opens (to come
    back to it)."""
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
        # A list, or where to fetch it ({url}).
        "resources": _resources(resources),
        "resource": dict(resource) if resource else None,
        "urlState": url_state,
        "urlParams": {"view": "ec-view", "date": "ec-date", **(url_params or {})},
        "urlViews": dict(url_views or {}),
        "highlightToday": highlight_today,
        "datePicker": date_picker,
        "moves": moves,
        "moveMode": move_mode,
        "outsideHours": outside_hours,
        "returnParam": return_param,
        "locale": language,
        "firstDay": int(formats.get_format("FIRST_DAY_OF_WEEK")),
        "timeZone": site_time_zone(),
        "texts": calendar_texts(),
        "options": dict(options or {}),
    }
