"""``{% ec_calendar %}``: a calendar on a page.

{% load ec_calendar %}
{% ec_calendar_media %}  {# in <head> #}
{% url "booking-events" as events %}
{% ec_calendar events view="timeGridWeek" %}
"""

from __future__ import annotations

from itertools import count
from typing import Any

from django import template
from django.template.loader import render_to_string
from django.utils.safestring import SafeString

from ..config import calendar_config, calendar_media

register = template.Library()

_ids = count(1)


@register.simple_tag
def ec_calendar_media() -> SafeString:
    """EventCalendar's stylesheet and script, and the package's."""
    return SafeString(str(calendar_media()))


@register.simple_tag(takes_context=True)
def ec_calendar(
    context: template.Context,
    events: str,
    view: str = "dayGridMonth",
    views: str = "dayGridMonth timeGridWeek timeGridDay listMonth",
    id: str = "",  # noqa: A002 - the element's.
    resources: bool = False,
    url_state: bool = True,
    highlight_today: bool = True,
    **options: Any,
) -> SafeString:
    """A calendar of the events at ``events`` (an ``EventFeedView``'s URL):
    opening on ``view``, switching between ``views`` (separated by spaces;
    empty: none), and any other of EventCalendar's options as keywords
    (``firstDay=1``, ``slotMinTime="08:00"``).

    ``resources``: its resources too, from the same view (``?resources=1``),
    for the resource views. ``url_state``: its view and date in the page's
    URL. ``highlight_today``: today tinted (never in a day's view)."""
    separator = "&" if "?" in events else "?"
    config = calendar_config(
        context["request"],
        events=events,
        view=view,
        views=views.split(),
        resources={"url": f"{events}{separator}resources=1"} if resources else None,
        url_state=url_state,
        highlight_today=highlight_today,
        options=options,
    )
    element = id or f"ec-calendar-{next(_ids)}"
    return SafeString(
        render_to_string(
            "django_ec_calendar/calendar.html",
            {"id": element, "config": config},
        )
    )
