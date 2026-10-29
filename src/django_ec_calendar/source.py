"""What a calendar shows: objects as EventCalendar's events, and back.

EventCalendar's events are plain objects (``{id, title, start, end,
allDay, ...}``). Times go as the wall-clock time of Django's current time
zone, without an offset, and come back so: what the calendar shows and
sends doesn't depend on the browser's time zone. A ``DateField`` is an
all-day date; EventCalendar's end is exclusive (the day after), a model's
end date is the last day.
"""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING, Any

from django.contrib.admin.utils import label_for_field, lookup_field
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models import Q
from django.utils import formats, timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.utils.translation import gettext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.models import Model, QuerySet
    from django.http import HttpRequest

ONE_DAY = datetime.timedelta(days=1)

#: The resource of the events without one (a nullable field's empty value).
NO_RESOURCE = "__none__"

#: A closed time, as a background event's class.
CLOSED = "django-ec-calendar-closed"

#: A day of the week as EventCalendar (and JavaScript) counts them: Sunday 0.
Weekday = int


def _clock(value: str, *, end: bool = False) -> datetime.timedelta:
    """``"09:30"`` as the time from midnight (``"24:00"``: the day's end)."""
    if end and value in ("24:00", "24:00:00"):
        return ONE_DAY
    moment = parse_time(value)
    if moment is None:
        raise ImproperlyConfigured(f"Business hours: {value!r} isn't a time.")
    return datetime.timedelta(
        hours=moment.hour, minutes=moment.minute, seconds=moment.second
    )


def _wall_clock(value: Any) -> datetime.datetime:
    """A datetime (aware: in the current time zone) or a date (its midnight)
    as a wall-clock time, without a time zone."""
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.replace(tzinfo=None)
    return datetime.datetime.combine(value, datetime.time())


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


def display_value(value: Any, field: Any = None) -> str:
    """A value as text, as the admin shows it (a choice's label, a date in
    the current language and time zone, "Yes"/"No"); "": none."""
    if value is None or value == "":
        return ""
    choices = getattr(field, "flatchoices", None)
    if choices:
        return str(dict(choices).get(value, value))
    if isinstance(value, bool):
        return gettext("Yes") if value else gettext("No")
    if isinstance(value, datetime.datetime) and timezone.is_aware(value):
        value = timezone.localtime(value)
    return str(formats.localize(value))


class CalendarSource:
    """Objects of a model as events, by their fields::

        class BookingSource(CalendarSource):
            calendar_start_field = "start"
            calendar_end_field = "end"  # optional

    ``calendar_start_field`` is a ``DateTimeField`` (events at a time) or a
    ``DateField`` (all-day events); it ends at ``calendar_end_field``, or
    after ``calendar_duration_field`` (minutes, or a ``DurationField``).
    ``calendar_all_day_field``, a ``BooleanField`` that makes a
    ``DateTimeField``'s event an all-day one. ``calendar_title_field`` (else
    ``str(obj)``), ``calendar_color_field`` (a CSS color) and
    ``calendar_detail_fields`` (more lines of text) say how it shows;
    ``calendar_resource_field``, in which resource (a column of the resource
    views) it is. ``get_calendar_event()`` makes the whole event, and
    ``get_calendar_resources()`` the resources.
    """

    #: The field where it starts: a ``DateTimeField`` or a ``DateField``.
    calendar_start_field: str = ""
    #: Where it ends (none: ``calendar_duration_field``, or no end).
    calendar_end_field: str | None = None
    #: How long it lasts, instead of an end: minutes (an integer field) or a
    #: ``DurationField``.
    calendar_duration_field: str | None = None
    #: Without an end field, the longest an event may last: one that starts
    #: that long before the calendar's range is still looked for.
    calendar_max_duration = datetime.timedelta(days=1)
    #: A ``BooleanField``: true, an all-day event (of a ``DateTimeField``).
    calendar_all_day_field: str | None = None
    #: Its title (none: ``str(obj)``).
    calendar_title_field: str | None = None
    #: Its color, a CSS color (none: the calendar's).
    calendar_color_field: str | None = None
    #: More of it, under its title: fields, methods or properties of the model
    #: (as ``list_display``'s), as text.
    calendar_detail_fields: Sequence[str] = ()
    #: In which resource it is: a ``ForeignKey``, a ``ManyToManyField`` (in
    #: several) or a field with ``choices``.
    calendar_resource_field: str | None = None
    #: The resource of those without one (a nullable field's); none:
    #: "No <field>".
    calendar_resource_empty_label: str | None = None
    #: When it's open: ``[{"days": [1, 2, 3, 4, 5], "start": "09:00", "end":
    #: "14:00"}, ...]`` (days as JavaScript counts them: Sunday 0; no days:
    #: every day). The rest is shaded. None: no hours.
    calendar_business_hours: Sequence[dict[str, Any]] | None = None
    #: Out of its hours (and its closed times): ``"shade"`` (shown as closed)
    #: or ``"block"`` (also not to be selected, nor moved to).
    calendar_outside_hours = "shade"
    #: Whether the time views show only the business hours' times and days.
    calendar_fit_hours = True

    def get_source_model(self) -> type[Model]:
        return self.model  # type: ignore[attr-defined]

    def _field(self, name: str | None) -> Any:
        if not name:
            return None
        try:
            return self.get_source_model()._meta.get_field(name)
        except FieldDoesNotExist as error:
            raise ImproperlyConfigured(
                f"{type(self).__name__}: {name!r} isn't a field of the model."
            ) from error

    @property
    def dates_only(self) -> bool:
        """Whether its events are days (a ``DateField``), not times."""
        field = self._field(self.calendar_start_field)
        if field is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__}.calendar_start_field is needed."
            )
        return not isinstance(field, models.DateTimeField)

    @property
    def has_end(self) -> bool:
        """Whether its events have an end one can change (an end field, or a
        duration)."""
        return bool(self.calendar_end_field or self.calendar_duration_field)

    # From the database --------------------------------------------------------

    def in_range(
        self,
        queryset: QuerySet[Any],
        start: datetime.datetime | datetime.date | None,
        end: datetime.datetime | datetime.date | None,
    ) -> QuerySet[Any]:
        """The objects of ``queryset`` the range ``[start, end)`` shows:
        those that start before its end, and end (or start) after its start.
        With a duration and no end field, those that start up to
        ``calendar_max_duration`` before it."""
        start, end = self._to_db(start), self._to_db(end)
        begins = self.calendar_start_field
        if end is not None:
            queryset = queryset.filter(**{f"{begins}__lt": end})
        if start is not None:
            if self.calendar_end_field:
                queryset = queryset.filter(
                    Q(**{f"{begins}__gte": start})
                    | Q(**{f"{self.calendar_end_field}__gte": start})
                )
            elif self.calendar_duration_field:
                queryset = queryset.filter(
                    **{f"{begins}__gte": start - self.calendar_max_duration}
                )
            else:
                queryset = queryset.filter(**{f"{begins}__gte": start})
        if self.calendar_resource_field and self._resource_kind() == "many":
            queryset = queryset.prefetch_related(self.calendar_resource_field)
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
        return str(value.isoformat())

    def _duration(self, obj: Model) -> datetime.timedelta | None:
        value = getattr(obj, self.calendar_duration_field or "", None)
        if value is None or isinstance(value, datetime.timedelta):
            return value
        return datetime.timedelta(minutes=value)

    def get_calendar_event_end(self, obj: Model) -> Any:
        """Where it ends: its end field, or its start and its duration;
        None: it has none."""
        if self.calendar_end_field:
            return getattr(obj, self.calendar_end_field)
        duration = self._duration(obj) if self.calendar_duration_field else None
        if duration is None:
            return None
        return getattr(obj, self.calendar_start_field) + duration

    def get_calendar_detail_fields(self, request: HttpRequest) -> Sequence[str]:
        """The details of the events, for this request
        (``calendar_detail_fields``)."""
        return self.calendar_detail_fields

    def get_calendar_details(
        self, request: HttpRequest, obj: Model
    ) -> list[dict[str, str]]:
        """``get_calendar_detail_fields()``' labels and values, as text (those
        without a value left out)."""
        details = []
        for name in self.get_calendar_detail_fields(request):
            field, attr, value = lookup_field(name, obj, self)  # type: ignore[arg-type]
            text = display_value(value, field)
            if text:
                details.append(
                    {"label": self._detail_label(name, type(obj)), "value": text}
                )
        return details

    def _detail_label(self, name: str, model: type[Model]) -> str:
        """A detail's label: its field's (``get_<field>_display``, a choice's
        field's too), or ``list_display``'s."""
        display = re.fullmatch(r"get_(\w+)_display", name)
        if display:
            try:
                field = model._meta.get_field(display.group(1))
                return str(getattr(field, "verbose_name", display.group(1)))
            except FieldDoesNotExist:
                pass
        return str(label_for_field(name, model, self))  # type: ignore[call-overload]

    def get_calendar_event(self, request: HttpRequest, obj: Model) -> dict[str, Any]:
        """``obj`` as an EventCalendar event."""
        start = getattr(obj, self.calendar_start_field)
        end = self.get_calendar_event_end(obj)
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
        details = self.get_calendar_details(request, obj)
        if details:
            event.setdefault("extendedProps", {})["details"] = details
        if self.calendar_resource_field:
            event["resourceIds"] = self.get_calendar_resource_ids(obj)
        return event

    def get_calendar_events(
        self, request: HttpRequest, queryset: QuerySet[Any]
    ) -> list[dict[str, Any]]:
        """The events of the objects the calendar's range shows
        (``?start=&end=``, as it asks for them)."""
        start = parse_moment(request.GET.get("start"))
        end = parse_moment(request.GET.get("end"))
        found = self.in_range(queryset, start, end)
        events = [self.get_calendar_event(request, obj) for obj in found]
        if start is not None and end is not None:
            events += self.get_calendar_closed_events(request, start, end)
        return events

    # Business hours ---------------------------------------------------------------

    def get_calendar_business_hours(
        self, request: HttpRequest, resource: str | None = None
    ) -> Sequence[dict[str, Any]] | None:
        """When it's open, for this request, and for ``resource`` (a
        resource's id; None: the calendar's, in the views without
        resources): ``calendar_business_hours`` by default, for all. None:
        no hours (open always)."""
        return self.calendar_business_hours

    def get_calendar_closed(
        self,
        request: HttpRequest,
        start: datetime.date,
        end: datetime.date,
        resource: str | None = None,
    ) -> Sequence[tuple[Any, Any]]:
        """Closed times between the dates ``start`` and ``end`` (exclusive),
        besides the hours: holidays, holidays of ``resource``… As ``(start,
        end)``: datetimes, or dates (whole days, shown in the month views
        too). None by default."""
        return ()

    def _days(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> tuple[datetime.date, datetime.date]:
        """The dates a range covers (its end exclusive, the day after when it
        ends in the day)."""
        first, last = _wall_clock(start), _wall_clock(end)
        after = last.date() if last.time() == datetime.time() else last.date() + ONE_DAY
        return first.date(), after

    def get_calendar_closed_ranges(
        self,
        request: HttpRequest,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
        resource: str | None = None,
    ) -> list[tuple[datetime.datetime, datetime.datetime, bool]]:
        """When it's closed, in the days of ``[start, end)``: out of its
        hours, and ``get_calendar_closed()``; as wall-clock times, and
        whether it's a whole day."""
        first, after = self._days(start, end)
        ranges: list[tuple[datetime.datetime, datetime.datetime, bool]] = []
        hours = self.get_calendar_business_hours(request, resource)
        if hours is not None and not self.dates_only:
            day = first
            while day < after:
                midnight = datetime.datetime.combine(day, datetime.time())
                weekday = (day.weekday() + 1) % 7
                opened = sorted(
                    (_clock(item["start"]), _clock(item["end"], end=True))
                    for item in hours
                    if weekday in item.get("days", range(7))
                )
                cursor = datetime.timedelta()
                for opens, closes in opened:
                    if opens > cursor:
                        ranges.append((midnight + cursor, midnight + opens, False))
                    cursor = max(cursor, closes)
                if cursor < ONE_DAY:
                    ranges.append((midnight + cursor, midnight + ONE_DAY, False))
                day += ONE_DAY
        for begins, ends in self.get_calendar_closed(request, first, after, resource):
            whole = not isinstance(begins, datetime.datetime)
            ranges.append((_wall_clock(begins), _wall_clock(ends), whole))
        return ranges

    def _closed_resources(self, request: HttpRequest) -> list[str | None]:
        """Whose hours there are: the calendar's (None), and each resource's."""
        resources: list[str | None] = [None]
        if self.calendar_resource_field:
            resources += [item["id"] for item in self.get_calendar_resources(request)]
        return resources

    def get_calendar_closed_events(
        self,
        request: HttpRequest,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> list[dict[str, Any]]:
        """The closed times of ``[start, end)``, as background events: the
        calendar's, and each resource's (in its column). A whole day is an
        all-day one (for the month views), and the same times (for the time
        views, whose all-day row is apart)."""
        events = []
        for resource in self._closed_resources(request):
            for begins, ends, whole in self.get_calendar_closed_ranges(
                request, start, end, resource
            ):
                shown = [(False, begins, ends)]
                if whole:
                    shown.append((True, begins, ends))
                for all_day, first, last in shown:
                    event: dict[str, Any] = {
                        "start": first.date().isoformat()
                        if all_day
                        else self.format_moment(first),
                        "end": last.date().isoformat()
                        if all_day
                        else self.format_moment(last),
                        "allDay": all_day,
                        "display": "background",
                        "classNames": [CLOSED],
                        "extendedProps": {"closed": True},
                    }
                    if resource is not None:
                        event["resourceIds"] = [resource]
                    events.append(event)
        return events

    def is_calendar_open(
        self,
        request: HttpRequest,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime | None,
        resource: str | None = None,
    ) -> bool:
        """Whether ``[start, end)`` is in its hours, for ``resource`` (and
        none of its closed times)."""
        begins = _wall_clock(start)
        ends = _wall_clock(end) if end is not None else begins
        if ends <= begins:
            ends = begins + datetime.timedelta(microseconds=1)
        return not any(
            closed_start < ends and closed_end > begins
            for closed_start, closed_end, _ in self.get_calendar_closed_ranges(
                request, begins, ends, resource
            )
        )

    def get_calendar_hours_options(self, request: HttpRequest) -> dict[str, Any]:
        """EventCalendar's options that fit the time views to the business
        hours (``calendar_fit_hours``): from the first time it opens to the
        last (``slotMinTime``, ``slotMaxTime``), without the days it's
        closed (``hiddenDays``); of the calendar and its resources."""
        if not self.calendar_fit_hours or self.dates_only:
            return {}
        hours: list[dict[str, Any]] = []
        for resource in self._closed_resources(request):
            hours += list(self.get_calendar_business_hours(request, resource) or ())
        if not hours:
            return {}

        def clock(delta: datetime.timedelta) -> str:
            seconds = int(delta.total_seconds())
            return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:00"

        days = set()
        for item in hours:
            days.update(item.get("days", range(7)))
        options: dict[str, Any] = {
            "slotMinTime": clock(min(_clock(item["start"]) for item in hours)),
            "slotMaxTime": clock(max(_clock(item["end"], end=True) for item in hours)),
        }
        hidden = [day for day in range(7) if day not in days]
        if hidden and len(hidden) < 7:
            options["hiddenDays"] = hidden
        return options

    # Resources ----------------------------------------------------------------

    def _resource_kind(self) -> str:
        """``"one"`` (a foreign key), ``"many"`` (many to many) or
        ``"choices"``."""
        field = self._field(self.calendar_resource_field)
        if field.many_to_many and not field.auto_created:
            return "many"
        if field.many_to_one or field.one_to_one:
            return "one"
        if getattr(field, "choices", None):
            return "choices"
        raise ImproperlyConfigured(
            f"{type(self).__name__}.calendar_resource_field: "
            f"{field.name!r} is a foreign key, a many-to-many field or a "
            "field with choices."
        )

    @property
    def resource_has_empty(self) -> bool:
        """Whether an event may be in no resource (a nullable foreign key, a
        blank many-to-many or choices field)."""
        field = self._field(self.calendar_resource_field)
        kind = self._resource_kind()
        if kind == "one":
            return bool(field.null)
        return bool(field.blank or field.null)

    def get_calendar_resource_empty_label(self, request: HttpRequest) -> str:
        if self.calendar_resource_empty_label is not None:
            return self.calendar_resource_empty_label
        field = self._field(self.calendar_resource_field)
        return gettext("No %(name)s") % {"name": field.verbose_name}

    def get_calendar_resources(self, request: HttpRequest) -> list[dict[str, Any]]:
        """The resources (EventCalendar's ``{id, title}``): the related
        objects a foreign key or a many-to-many field may point to (its
        ``limit_choices_to``), or a field's choices; and, when an event may
        be in none, a resource for those."""
        field = self._field(self.calendar_resource_field)
        if self._resource_kind() == "choices":
            resources = [
                {"id": str(value), "title": str(label)}
                for value, label in field.flatchoices
                if value not in ("", None)
            ]
        else:
            related = field.related_model._default_manager.complex_filter(
                field.get_limit_choices_to()
            )
            resources = [{"id": str(obj.pk), "title": str(obj)} for obj in related]
        if self.resource_has_empty:
            resources.append(
                {
                    "id": NO_RESOURCE,
                    "title": self.get_calendar_resource_empty_label(request),
                }
            )
        return resources

    def get_calendar_resource_ids(self, obj: Model) -> list[str]:
        """The resources ``obj`` is in (their ids)."""
        field = self._field(self.calendar_resource_field)
        kind = self._resource_kind()
        if kind == "many":
            ids = [str(related.pk) for related in getattr(obj, field.name).all()]
        else:
            value = getattr(obj, field.attname)
            ids = [] if value in (None, "") else [str(value)]
        return ids or ([NO_RESOURCE] if self.resource_has_empty else [])

    def resource_value(self, resource: str) -> Any:
        """A resource's id as its field takes it (a foreign key's, a
        choice's value; for no resource, its empty value)."""
        field = self._field(self.calendar_resource_field)
        if resource == NO_RESOURCE:
            return None if field.null else ""
        target = field.target_field if field.is_relation else field
        return target.to_python(resource)

    # Back from the calendar ---------------------------------------------------

    def moved_values(self, start: str | None, end: str | None) -> dict[str, Any] | None:
        """The fields' values for an event moved or resized to ``start`` and
        ``end`` (as the calendar sends them); None: not dates."""
        begins, ends = parse_moment(start), parse_moment(end)
        if begins is None or (end and ends is None):
            return None
        first = self._to_field(begins)
        values: dict[str, Any] = {self.calendar_start_field: first}
        if self.calendar_end_field:
            if ends is None:
                values[self.calendar_end_field] = None
            elif self.dates_only:
                # The calendar's end is the day after the last one.
                values[self.calendar_end_field] = self._to_field(ends) - ONE_DAY
            else:
                values[self.calendar_end_field] = self._to_field(ends)
        elif self.calendar_duration_field and ends is not None:
            duration = self._to_field(ends) - first
            field = self._field(self.calendar_duration_field)
            values[self.calendar_duration_field] = (
                duration
                if isinstance(field, models.DurationField)
                else round(duration.total_seconds() / 60)
            )
        return values

    def _to_field(self, moment: datetime.datetime | datetime.date) -> Any:
        if self.dates_only:
            return moment.date() if isinstance(moment, datetime.datetime) else moment
        return self._to_db(moment)
