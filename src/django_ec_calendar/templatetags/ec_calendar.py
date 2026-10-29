"""``{% ec_calendar %}``: a calendar on a page.

{% load ec_calendar %}
{% ec_calendar_media %}  {# in <head> #}
{% url "booking-events" as events %}
{% ec_calendar events view="timeGridWeek" %}
"""

from __future__ import annotations

from typing import Any

from django import template
from django.utils.safestring import SafeString

from ..config import calendar_config, calendar_media
from ..widget import Calendar

register = template.Library()


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
    view_param: str = "ec-view",
    date_param: str = "ec-date",
    highlight_today: bool = True,
    date_picker: bool = True,
    **options: Any,
) -> SafeString:
    """A calendar of the events at ``events`` (an ``EventFeedView``'s URL):
    opening on ``view``, switching between ``views`` (separated by spaces;
    empty: none), and any other of EventCalendar's options as keywords
    (``firstDay=1``, ``slotMinTime="08:00"``).

    ``resources``: its resources too, from the same view (``?resources=1``),
    for the resource views. ``url_state``: its view and date in the page's
    URL (``view_param``, ``date_param``: their names). ``highlight_today``:
    today tinted (never in a day's view).
    ``date_picker``: a date field in its toolbar, to go to a date."""
    separator = "&" if "?" in events else "?"
    config = calendar_config(
        context["request"],
        events=events,
        view=view,
        views=views.split(),
        resources={"url": f"{events}{separator}resources=1"} if resources else None,
        url_state=url_state,
        url_params={"view": view_param, "date": date_param},
        highlight_today=highlight_today,
        date_picker=date_picker,
        options=options,
    )
    return Calendar(config, id=id).render()


@register.simple_tag(takes_context=True)
def ec_calendar_inline(context: template.Context, inline_admin_formset: Any) -> Any:
    """A ``CalendarInline``'s calendar, of the object of its change page
    (``original``); None: it isn't saved yet."""
    inline = inline_admin_formset.opts
    return inline.get_calendar(context["request"], context.get("original"))
