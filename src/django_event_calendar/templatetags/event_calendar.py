"""``{% event_calendar %}``: a calendar on a page.

{% load event_calendar %}
{% event_calendar_media %}  {# in <head> #}
{% url "booking-events" as events %}
{% event_calendar events view="timeGridWeek" %}
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
def event_calendar_media() -> SafeString:
    """EventCalendar's stylesheet and script, and the package's."""
    return SafeString(str(calendar_media()))


@register.simple_tag(takes_context=True)
def event_calendar(
    context: template.Context,
    events: str,
    view: str = "dayGridMonth",
    views: str = "dayGridMonth timeGridWeek timeGridDay listMonth",
    id: str = "",  # noqa: A002 - the element's.
    **options: Any,
) -> SafeString:
    """A calendar of the events at ``events`` (an ``EventFeedView``'s URL):
    opening on ``view``, switching between ``views`` (separated by spaces;
    empty: none), and any other of EventCalendar's options as keywords
    (``firstDay=1``, ``slotMinTime="08:00"``)."""
    config = calendar_config(
        context["request"],
        events=events,
        view=view,
        views=views.split(),
        options=options,
    )
    element = id or f"event-calendar-{next(_ids)}"
    return SafeString(
        render_to_string(
            "django_event_calendar/calendar.html",
            {"id": element, "config": config},
        )
    )
