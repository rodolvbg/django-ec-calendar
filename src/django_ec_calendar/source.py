"""What a calendar shows: objects as EventCalendar's events, and back.

EventCalendar's events are plain objects (``{id, title, start, end,
allDay, ...}``). Times go as the wall-clock time of Django's current time
zone, without an offset, and the calendar is set to UTC: what it shows
and what it sends back don't depend on the browser's time zone. A
``DateField`` is an all-day date; EventCalendar's end is exclusive (the day
after), a model's end date is the last day.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest

ONE_DAY = datetime.timedelta(days=1)


def parse_moment(value: str | None) -> datetime.datetime | datetime.date | None:
    """An ISO date (``2026-10-29``) or a date and time (``2026-10-29T10:00``,
    as the calendar sends it); None: not one."""
    if not value:
        return None
    try:
        # A date first: newer Djangos read one as a datetime too.
        return parse_date(value) or parse_datetime(value)
    except ValueError:
        return None


class CalendarSource:
    """Objects of a model as events, by their fields::

        class BookingSource(CalendarSource):
            calendar_start_field = "start"
            calendar_end_field = "end"  # optional

    ``calendar_start_field`` (and ``calendar_end_field``) are
    ``DateTimeField`` (events at a time) or ``DateField`` (all-day events);
    ``calendar_all_day_field``, a ``BooleanField`` that makes a
    ``DateTimeField``'s event an all-day one. ``calendar_title_field`` (else
    ``str(obj)``) and ``calendar_color_field`` (a CSS color) say how it
    shows; ``get_calendar_event()`` makes the whole event.
    """

    #: The field where it starts: a ``DateTimeField`` or a ``DateField``.
    calendar_start_field: str = ""
    #: Where it ends (none: it lasts no time, or the day).
    calendar_end_field: str | None = None
    #: A ``BooleanField``: true, an all-day event (of a ``DateTimeField``).
    calendar_all_day_field: str | None = None
    #: Its title (none: ``str(obj)``).
    calendar_title_field: str | None = None
    #: Its color, a CSS color (none: the calendar's).
    calendar_color_field: str | None = None

    def get_source_model(self) -> type[Model]:
        return self.model  # type: ignore[attr-defined]

    def _field(self, name: str | None) -> models.Field[Any, Any] | None:
        if not name:
            return None
        try:
            field = self.get_source_model()._meta.get_field(name)
        except FieldDoesNotExist as error:
            raise ImproperlyConfigured(
                f"{type(self).__name__}: {name!r} isn't a field of the model."
            ) from error
        return field  # type: ignore[return-value]

    @property
    def dates_only(self) -> bool:
        """Whether its events are days (a ``DateField``), not times."""
        field = self._field(self.calendar_start_field)
        if field is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__}.calendar_start_field is needed."
            )
        return not isinstance(field, models.DateTimeField)

    # From the database --------------------------------------------------------

    def in_range(
        self,
        queryset: QuerySet[Any],
        start: datetime.datetime | datetime.date | None,
        end: datetime.datetime | datetime.date | None,
    ) -> QuerySet[Any]:
        """The objects of ``queryset`` the range ``[start, end)`` shows:
        those that start before its end, and end (or start) after its start."""
        start, end = self._to_db(start), self._to_db(end)
        begins = self.calendar_start_field
        if end is not None:
            queryset = queryset.filter(**{f"{begins}__lt": end})
        if start is not None:
            ends = Q(**{f"{begins}__gte": start})
            if self.calendar_end_field:
                ends |= Q(**{f"{self.calendar_end_field}__gte": start})
            queryset = queryset.filter(ends)
        return queryset

    def _to_db(
        self, moment: datetime.datetime | datetime.date | None
    ) -> datetime.datetime | datetime.date | None:
        """A moment of the calendar (a wall-clock time of the current time
        zone, or a date) as the start field compares it."""
        if moment is None:
            return None
        if self.dates_only:
            return moment.date() if isinstance(moment, datetime.datetime) else moment
        if not isinstance(moment, datetime.datetime):
            moment = datetime.datetime.combine(moment, datetime.time())
        if timezone.is_naive(moment) and timezone.is_aware(timezone.now()):
            moment = timezone.make_aware(moment)
        return moment

    # As events ----------------------------------------------------------------

    def format_moment(self, value: Any) -> str | None:
        """A field's value as the calendar reads it: a date, or the current
        time zone's wall-clock time (no offset)."""
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return value.replace(tzinfo=None).isoformat(timespec="seconds")
        return value.isoformat()

    def get_calendar_event(self, request: HttpRequest, obj: Model) -> dict[str, Any]:
        """``obj`` as an EventCalendar event."""
        start = getattr(obj, self.calendar_start_field)
        end = getattr(obj, self.calendar_end_field) if self.calendar_end_field else None
        all_day = self.dates_only or bool(
            self.calendar_all_day_field and getattr(obj, self.calendar_all_day_field)
        )
        if self.dates_only:
            # The calendar's end is exclusive: the day after the last one.
            end = (end or start) + ONE_DAY
        title = (
            getattr(obj, self.calendar_title_field)
            if self.calendar_title_field
            else obj
        )
        event: dict[str, Any] = {
            "id": str(obj.pk),
            "title": str(title),
            "start": self.format_moment(start),
            "allDay": all_day,
        }
        if end is not None:
            event["end"] = self.format_moment(end)
        color = (
            getattr(obj, self.calendar_color_field, None)
            if self.calendar_color_field
            else None
        )
        if color:
            event["color"] = str(color)
        return event

    def get_calendar_events(
        self, request: HttpRequest, queryset: QuerySet[Any]
    ) -> list[dict[str, Any]]:
        """The events of the objects the calendar's range shows
        (``?start=&end=``, as it asks for them)."""
        found = self.in_range(
            queryset,
            parse_moment(request.GET.get("start")),
            parse_moment(request.GET.get("end")),
        )
        return [self.get_calendar_event(request, obj) for obj in found]

    # Back from the calendar ---------------------------------------------------

    def moved_values(self, start: str | None, end: str | None) -> dict[str, Any] | None:
        """The fields' values for an event moved or resized to ``start`` and
        ``end`` (as the calendar sends them); None: not dates."""
        begins, ends = parse_moment(start), parse_moment(end)
        if begins is None or (end and ends is None):
            return None
        values: dict[str, Any] = {self.calendar_start_field: self._to_field(begins)}
        if self.calendar_end_field:
            if ends is None:
                values[self.calendar_end_field] = None
            elif self.dates_only:
                # The calendar's end is the day after the last one.
                values[self.calendar_end_field] = self._to_field(ends) - ONE_DAY
            else:
                values[self.calendar_end_field] = self._to_field(ends)
        return values

    def _to_field(self, moment: datetime.datetime | datetime.date) -> Any:
        if self.dates_only:
            return moment.date() if isinstance(moment, datetime.datetime) else moment
        return self._to_db(moment)
