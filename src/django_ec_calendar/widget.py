"""A calendar to show, in any template: ``{{ calendar.media }}`` (in the
page's ``<head>``) and ``{{ calendar }}``."""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Any

from django.template.loader import render_to_string
from django.utils.safestring import SafeString

from .config import calendar_media

if TYPE_CHECKING:
    from django.forms import Media

_ids = count(1)


class Calendar:
    """A calendar of its configuration (``calendar_config()``, or a view's
    ``get_calendar_config(request)``), its element's ``id`` (none: one of
    its own). Its ``media`` are EventCalendar's script and stylesheet, and
    the package's."""

    template_name = "django_ec_calendar/calendar.html"

    def __init__(self, config: dict[str, Any], id: str = "") -> None:  # noqa: A002
        self.config = config
        self.id = id or f"ec-calendar-{next(_ids)}"

    @property
    def media(self) -> Media:
        return calendar_media()

    def render(self) -> SafeString:
        return SafeString(
            render_to_string(self.template_name, {"id": self.id, "config": self.config})
        )

    def __str__(self) -> str:
        return self.render()

    def __html__(self) -> SafeString:
        return self.render()
