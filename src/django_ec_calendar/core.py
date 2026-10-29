"""A calendar's behaviour, wherever it is: its options for each request, who
may do what, its events, and moving them — for the admin
(``CalendarAdminMixin``) and for your own views (``CalendarView``) alike."""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_permission_codename
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db import transaction
from django.http import JsonResponse
from django.utils.translation import gettext

from .config import calendar_config
from .source import NO_RESOURCE, ONE_DAY, CalendarSource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.models import Model, QuerySet
    from django.http import HttpRequest

#: The page's URL's parameters with its view and date (``calendar_url_state``).
URL_PARAMS = {"view": "ec-view", "date": "ec-date"}

#: How dragging an event (or its end) goes: not at all, saved at once,
#: asked first, or kept until several are saved together.
MOVE_MODES = ("off", "save", "confirm", "batch")


class CalendarMoveError(Exception):
    """A move that can't be: why (``message``), and its HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclasses.dataclass
class CalendarMove:
    """A move checked (``prepare_calendar_move()``), to be saved: its object,
    with its new values set, the fields it changes, and with a many-to-many
    resource, from which to which (``many``)."""

    obj: Any
    names: list[str] = dataclasses.field(default_factory=list)
    many: tuple[str, str] | None = None


class CalendarMixin(CalendarSource):
    """A calendar of a model's objects: :class:`CalendarSource`'s fields, and
    how it behaves, each option with its method taking the request.

    Who may do what is ``has_calendar_view_permission()``,
    ``has_calendar_move_permission()`` and ``has_calendar_add_permission()``
    — by default, the user's model permissions (``view_``/``change_``,
    ``change_``, ``add_``). What it shows is ``get_calendar_queryset()``;
    where it is, ``get_calendar_urls()``.
    """

    #: The view it opens on.
    calendar_view = "dayGridMonth"
    #: The views one can switch between (none: only ``calendar_view``).
    calendar_views: Sequence[str] = (
        "dayGridMonth",
        "timeGridWeek",
        "timeGridDay",
        "listMonth",
    )
    #: How dragging an event, or its end, goes: ``"off"`` (it can't be: a
    #: slip of the mouse would change one), ``"save"`` (saved at once),
    #: ``"confirm"`` (asked first) or ``"batch"`` (kept, until several are
    #: saved together, or discarded).
    calendar_move_mode = "off"
    #: Whether dragging an event to another resource changes its resource.
    calendar_resource_editable = True
    #: Whether selecting dates opens the add page with them.
    calendar_selectable = True
    #: Whether its view and date go in its page's URL (``ec-view``,
    #: ``ec-date``): one comes back to the same place, and can share it.
    calendar_url_state = True
    #: Their names: ``{"view": "vista", "date": "fecha"}`` (those not given,
    #: ``URL_PARAMS``').
    calendar_url_params: dict[str, str] = {}  # noqa: RUF012
    #: The views' names in it: ``{"timeGridWeek": "semana"}`` (those not
    #: given, their own).
    calendar_url_views: dict[str, str] = {}  # noqa: RUF012
    #: Whether today is tinted (never in a day's view).
    calendar_highlight_today = True
    #: Whether its toolbar has a date field, to go to a date.
    calendar_date_picker = True
    #: Any other of EventCalendar's options (JSON).
    calendar_options: dict[str, Any] = {}  # noqa: RUF012
    #: Errors of ``get_calendar_queryset()`` that are the request's (a filter
    #: it doesn't know): answered with a 400.
    calendar_queryset_errors: tuple[type[Exception], ...] = ()

    # Its options, for each request -------------------------------------------

    def get_calendar_view(self, request: HttpRequest) -> str:
        """The view it opens on (``calendar_view``)."""
        return self.calendar_view

    def get_calendar_views(self, request: HttpRequest) -> Sequence[str]:
        """The views one can switch between (``calendar_views``)."""
        return self.calendar_views

    def get_calendar_move_mode(self, request: HttpRequest) -> str:
        """How dragging goes, for this request (``calendar_move_mode``):
        ``"off"``, ``"save"``, ``"confirm"`` or ``"batch"``."""
        mode = self.calendar_move_mode
        if mode not in MOVE_MODES:
            raise ImproperlyConfigured(
                f"{type(self).__name__}.calendar_move_mode is one of "
                f"{', '.join(MOVE_MODES)}, not {mode!r}."
            )
        return mode

    def get_calendar_resource_editable(self, request: HttpRequest) -> bool:
        """Whether a move may change an event's resource
        (``calendar_resource_editable``, and its field is editable)."""
        field = self._field(self.calendar_resource_field)
        return bool(self.calendar_resource_editable and field.editable)

    def get_calendar_url_state(self, request: HttpRequest) -> bool:
        """Whether its view and date go in its page's URL
        (``calendar_url_state``)."""
        return self.calendar_url_state

    def get_calendar_url_params(self, request: HttpRequest) -> dict[str, str]:
        """The names of the URL's parameters with its view (``view``) and
        date (``date``): ``calendar_url_params``, over ``URL_PARAMS``."""
        return {**URL_PARAMS, **self.calendar_url_params}

    def get_calendar_url_views(self, request: HttpRequest) -> dict[str, str]:
        """The views' names in the URL (``calendar_url_views``)."""
        return dict(self.calendar_url_views)

    def get_calendar_highlight_today(self, request: HttpRequest) -> bool:
        """Whether today is tinted (``calendar_highlight_today``)."""
        return self.calendar_highlight_today

    def get_calendar_date_picker(self, request: HttpRequest) -> bool:
        """Whether its toolbar has a date field (``calendar_date_picker``)."""
        return self.calendar_date_picker

    def get_calendar_options(self, request: HttpRequest) -> dict[str, Any]:
        """Any other of EventCalendar's options (``calendar_options``): what
        the calendar shows, not what the server allows (that has its own
        methods). Over those fitted to the business hours."""
        return dict(self.calendar_options)

    # Who may do what ---------------------------------------------------------

    def _has_model_permission(self, request: HttpRequest, action: str) -> bool:
        user = getattr(request, "user", None)
        if user is None:
            return False
        opts = self.get_source_model()._meta
        return bool(
            user.has_perm(f"{opts.app_label}.{get_permission_codename(action, opts)}")
        )

    def has_calendar_view_permission(self, request: HttpRequest) -> bool:
        """Whether one may see the calendar and its events: one may view or
        change the model's objects."""
        return self._has_model_permission(
            request, "view"
        ) or self._has_model_permission(request, "change")

    def has_calendar_move_permission(
        self, request: HttpRequest, obj: Model | None = None
    ) -> bool:
        """Whether one may drag ``obj`` (none: any event) to change it: its
        mode isn't ``"off"``, and one may change the model's objects."""
        return bool(
            self.get_calendar_move_mode(request) != "off"
            and self._has_model_permission(request, "change")
        )

    def has_calendar_add_permission(self, request: HttpRequest) -> bool:
        """Whether selecting dates opens the add page with them:
        ``calendar_selectable``, an add page (``get_calendar_urls()``), and
        one may add."""
        return bool(
            self.calendar_selectable and self._has_model_permission(request, "add")
        )

    # What it shows, and where ------------------------------------------------

    def get_calendar_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        """What the calendar shows (its range, of these): by default, all of
        the model's."""
        return self.get_source_model()._default_manager.all()

    def get_calendar_urls(self, request: HttpRequest) -> dict[str, str | None]:
        """Where its events are (``events``), where a move is saved
        (``move``), and several (``moves``), and its add page (``add``, which
        gets the dates as ``?start=&end=``)."""
        raise NotImplementedError

    def get_calendar_params(self, request: HttpRequest) -> dict[str, str]:
        """What its events' requests take too (filters)."""
        return {}

    def get_calendar_return_param(self, request: HttpRequest) -> str | None:
        """The parameter that takes the calendar's URL to the pages it opens,
        to come back to it (none: not taken)."""
        return None

    def get_calendar_event_url(self, request: HttpRequest, obj: Model) -> str | None:
        """Where clicking it leads: its ``get_absolute_url()``, if it has
        one."""
        url = getattr(obj, "get_absolute_url", None)
        return url() if callable(url) else None

    def get_calendar_event(self, request: HttpRequest, obj: Model) -> dict[str, Any]:
        """An event, with where clicking it leads and whether it may be
        dragged."""
        event = super().get_calendar_event(request, obj)
        url = self.get_calendar_event_url(request, obj)
        if url:
            event.setdefault("extendedProps", {})["url"] = url
        event["editable"] = self.has_calendar_move_permission(request, obj)
        if not self.has_end:
            event["durationEditable"] = False  # No end to change.
        return event

    def get_calendar_initial(self, request: HttpRequest) -> dict[str, Any]:
        """The values of a new object, from the calendar's add link
        (``?start=&end=``, and the resource's field): its fields' as they
        take them. For an add page's ``initial``."""
        values = self.moved_values(request.GET.get("start"), request.GET.get("end"))
        initial = {
            name: value for name, value in (values or {}).items() if value is not None
        }
        resource = self.calendar_resource_field
        if resource and request.GET.get(resource):
            initial[resource] = request.GET[resource]
        return initial

    # Its configuration -------------------------------------------------------

    def get_calendar_config(self, request: HttpRequest) -> dict[str, Any]:
        """The calendar's configuration, for its script."""
        urls = self.get_calendar_urls(request)
        add = urls.get("add") if self.has_calendar_add_permission(request) else None
        mode = self.get_calendar_move_mode(request)
        movable = self.has_calendar_move_permission(request)
        move = urls.get("move") if movable else None
        moves = urls.get("moves") if movable and mode == "batch" else None
        resources = resource = None
        if self.calendar_resource_field:
            field = self._field(self.calendar_resource_field)
            resources = self.get_calendar_resources(request)
            message = gettext("It can't be moved to another %(name)s.")
            resource = {
                "param": field.name,
                "empty": NO_RESOURCE,
                "editable": self.get_calendar_resource_editable(request),
                "message": message % {"name": field.verbose_name},
            }
        return calendar_config(
            request,
            events=str(urls["events"]),
            params=self.get_calendar_params(request),
            view=self.get_calendar_view(request),
            views=self.get_calendar_views(request),
            add=add,
            move=move,
            moves=moves,
            move_mode=mode if movable else "off",
            dates_only=self.dates_only,
            resources=resources,
            resource=resource,
            url_state=self.get_calendar_url_state(request),
            url_params=self.get_calendar_url_params(request),
            url_views=self.get_calendar_url_views(request),
            highlight_today=self.get_calendar_highlight_today(request),
            date_picker=self.get_calendar_date_picker(request),
            outside_hours=self.calendar_outside_hours,
            return_param=self.get_calendar_return_param(request),
            # Fitted to the business hours, unless its own options say.
            options={
                **self.get_calendar_hours_options(request),
                **self.get_calendar_options(request),
            },
        )

    def get_calendar(self, request: HttpRequest, id: str = "") -> Any:  # noqa: A002
        """The calendar, to show it: ``{{ calendar.media }}`` and
        ``{{ calendar }}`` (its element's ``id``)."""
        from .widget import Calendar

        return Calendar(self.get_calendar_config(request), id=id)

    # Moves -------------------------------------------------------------------

    def prepare_calendar_move(
        self,
        request: HttpRequest,
        move: dict[str, Any],
        queryset: QuerySet[Any] | None = None,
    ) -> CalendarMove:
        """An event moved (``move``: ``pk``, ``start``, ``end`` as the
        calendar sends them; to another resource, ``resource`` and
        ``resource_from``), checked but not saved. Raises
        ``CalendarMoveError`` (its message, and its HTTP status) when it
        can't be."""
        if queryset is None:
            queryset = self.get_calendar_queryset(request)
        try:
            obj = queryset.filter(pk=move.get("pk")).first()
        except (ValueError, TypeError, ValidationError):
            obj = None
        if obj is None:
            raise CalendarMoveError(gettext("It doesn't exist any more."), 404)
        if not self.has_calendar_move_permission(request, obj):
            raise CalendarMoveError(gettext("You may not move it."), 403)
        values = self.moved_values(move.get("start"), move.get("end"))
        if values is None:
            raise CalendarMoveError(gettext("Not a date."))
        prepared = CalendarMove(obj=obj, names=list(values))
        resource = move.get("resource")
        if resource is not None and self.calendar_resource_field:
            field = self._field(self.calendar_resource_field)
            if not self.get_calendar_resource_editable(request):
                message = gettext("It can't be moved to another %(name)s.")
                raise CalendarMoveError(message % {"name": field.verbose_name})
            resource = str(resource)
            if resource not in {
                item["id"] for item in self.get_calendar_resources(request)
            }:
                message = gettext("Unknown %(name)s.")
                raise CalendarMoveError(message % {"name": field.verbose_name})
            if self._resource_kind() == "many":
                prepared.many = (
                    str(move.get("resource_from") or NO_RESOURCE),
                    resource,
                )
            else:
                values[field.attname] = self.resource_value(resource)
                prepared.names.append(field.name)
        for name, value in values.items():
            setattr(obj, name, value)
        if self.calendar_outside_hours == "block" and not self._open_for(
            request, obj, resource
        ):
            raise CalendarMoveError(gettext("It's out of the business hours."))
        try:
            # What it changes as the model checks it (and its clean()).
            obj.full_clean(
                exclude=[
                    field.name
                    for field in obj._meta.fields
                    if field.name not in prepared.names
                ],
                validate_unique=False,
            )
        except ValidationError as error:
            raise CalendarMoveError(" ".join(error.messages)) from error
        return prepared

    def save_calendar_object(
        self, request: HttpRequest, obj: Model, names: list[str]
    ) -> None:
        """Save a moved object (``names``: the fields it changes):
        ``obj.save()`` by default."""
        obj.save()

    def log_calendar_move(
        self, request: HttpRequest, obj: Model, names: list[str]
    ) -> None:
        """After a move is saved (``names``: what it changed): nothing by
        default."""

    def save_calendar_move(self, request: HttpRequest, move: CalendarMove) -> None:
        """A move checked by ``prepare_calendar_move()``, saved
        (``save_calendar_object()``, and a many-to-many resource) and logged
        (``log_calendar_move()``)."""
        obj, names = move.obj, list(move.names)
        self.save_calendar_object(request, obj, names)
        if move.many:
            name = str(self.calendar_resource_field)
            related = getattr(obj, name)
            old, new = move.many
            if old != NO_RESOURCE:
                related.remove(self.resource_value(old))
            if new != NO_RESOURCE:
                related.add(self.resource_value(new))
            names.append(name)
        self.log_calendar_move(request, obj, names)

    def _open_for(self, request: HttpRequest, obj: Model, resource: str | None) -> bool:
        """Whether ``obj``, where it's been moved, is in the hours: of
        ``resource`` (where it's been moved to), else of its own."""
        start = getattr(obj, self.calendar_start_field)
        end = self.get_calendar_event_end(obj)
        if self.dates_only:
            end = (end or start) + ONE_DAY
        if resource is not None:
            resources: list[str | None] = [resource]
        elif self.calendar_resource_field:
            resources = list(self.get_calendar_resource_ids(obj))
        else:
            resources = [None]
        return all(
            self.is_calendar_open(request, start, end, item) for item in resources
        )

    # Its endpoints -----------------------------------------------------------

    def calendar_events_response(self, request: HttpRequest) -> JsonResponse:
        """The events of ``?start=&end=``, of ``get_calendar_queryset()``."""
        if not self.has_calendar_view_permission(request):
            raise PermissionDenied
        try:
            queryset = self.get_calendar_queryset(request)
        except self.calendar_queryset_errors:
            return JsonResponse({"error": gettext("Unknown filter.")}, status=400)
        return JsonResponse(self.get_calendar_events(request, queryset), safe=False)

    def calendar_move_response(self, request: HttpRequest) -> JsonResponse:
        """An event dragged, or its end (POST): ``pk``, ``start`` and ``end``
        (as the calendar sends them); to another resource, ``resource`` (and
        ``resource_from``, the one it was dragged from)."""
        try:
            move = self.prepare_calendar_move(request, request.POST.dict())
        except self.calendar_queryset_errors:
            move = None
            error = CalendarMoveError(gettext("It doesn't exist any more."), 404)
        except CalendarMoveError as problem:
            move, error = None, problem
        if move is None:
            if error.status == 403:
                raise PermissionDenied
            return JsonResponse({"error": error.message}, status=error.status)
        self.save_calendar_move(request, move)
        return JsonResponse({"event": self.get_calendar_event(request, move.obj)})

    def calendar_moves_response(self, request: HttpRequest) -> JsonResponse:
        """Several moves, saved together (``"batch"``; POST): a JSON body,
        ``{"moves": [{pk, start, end, resource?, resource_from?}, ...]}``.
        All of them are checked first: with any that can't be, none is
        saved, and ``errors`` says which (``{pk: message}``); else all are,
        in a transaction."""
        if self.get_calendar_move_mode(request) != "batch":
            raise PermissionDenied
        try:
            moves = json.loads(request.body or b"{}")["moves"]
            if not isinstance(moves, list):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            return JsonResponse({"error": gettext("Not a list of moves.")}, status=400)
        try:
            queryset = self.get_calendar_queryset(request)
        except self.calendar_queryset_errors:
            return JsonResponse({"error": gettext("Unknown filter.")}, status=400)
        prepared, errors = [], {}
        for move in moves:
            try:
                prepared.append(
                    self.prepare_calendar_move(request, dict(move), queryset)
                )
            except CalendarMoveError as error:
                errors[str(move.get("pk"))] = error.message
            except (TypeError, ValueError, AttributeError):
                return JsonResponse(
                    {"error": gettext("Not a list of moves.")}, status=400
                )
        if errors:
            return JsonResponse({"errors": errors}, status=400)
        with transaction.atomic():
            for move in prepared:
                self.save_calendar_move(request, move)
        return JsonResponse(
            {
                "events": [
                    self.get_calendar_event(request, move.obj) for move in prepared
                ]
            }
        )
