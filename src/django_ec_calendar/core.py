"""A calendar's behaviour, wherever it is: its options for each request, who
may do what, its events, and moving them — for the admin
(``CalendarAdminMixin``) and for your own views (``CalendarView``) alike."""

from __future__ import annotations

import copy
import dataclasses
import json
from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth import get_permission_codename
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db import transaction
from django.http import JsonResponse
from django.utils.http import urlencode
from django.utils.translation import gettext

from .config import calendar_config, translations
from .source import NO_RESOURCE, ONE_DAY, CalendarSource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.models import Model, QuerySet
    from django.http import HttpRequest

#: The page's URL's parameters with its view and date (``calendar_url_state``).
URL_PARAMS = {"view": "ec-view", "date": "ec-date", "resources": "ec-resources"}

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
    #: Whether a move that was saved can be undone, for ``calendar_undo_seconds``
    #: after it (a bar with "Undo", and Ctrl/Cmd+Z): the opposite move, sent
    #: and checked as any other, and refused if the event changed since.
    calendar_undo = True
    #: How long, in seconds, a saved move can be undone.
    calendar_undo_seconds = 10
    #: Whether dragging an event to another resource changes its resource.
    calendar_resource_editable = True
    #: The other fields its resources may be of, chosen by its URL
    #: (``?ec-resources=room``: ``get_calendar_url_params()``'s
    #: ``resources``); without it, ``calendar_resource_field``.
    calendar_resource_fields: Sequence[str] = ()
    #: Whether selecting dates opens the add page with them.
    calendar_selectable = True
    #: Whether its view and date go in its page's URL (``ec-view``,
    #: ``ec-date``): one comes back to the same place, and can share it.
    calendar_url_state = True
    #: Their names: ``{"view": "vista", "date": "fecha"}`` (those not given,
    #: ``URL_PARAMS``'). Translatable (``gettext_lazy``), as the views' and
    #: the fields' names: the active language's, and any other's still read.
    calendar_url_params: dict[str, Any] = {}  # noqa: RUF012
    #: The views' names in it: ``{"timeGridWeek": "semana"}`` (those not
    #: given, their own).
    calendar_url_views: dict[str, Any] = {}  # noqa: RUF012
    #: The fields of ``calendar_resource_fields``' names in it:
    #: ``{"room": "gabinete"}`` (those not given, their own).
    calendar_url_resources: dict[str, Any] = {}  # noqa: RUF012
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

    def get_calendar_undo_seconds(self, request: HttpRequest) -> int:
        """How long a saved move can be undone, for this request
        (``calendar_undo`` and ``calendar_undo_seconds``); 0: not at all."""
        if not self.calendar_undo:
            return 0
        return max(0, int(self.calendar_undo_seconds))

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
        """The names of the URL's parameters with its view (``view``), date
        (``date``) and the field of its resources (``resources``):
        ``calendar_url_params``, over ``URL_PARAMS``; in the active
        language."""
        names = {**URL_PARAMS, **self.calendar_url_params}
        return {key: str(name) for key, name in names.items()}

    def get_calendar_url_resources(self, request: HttpRequest) -> dict[str, str]:
        """The fields' names in the URL (``calendar_url_resources``), in the
        active language."""
        return {field: str(name) for field, name in self.calendar_url_resources.items()}

    def get_calendar_url_aliases(
        self, request: HttpRequest
    ) -> dict[str, dict[str, list[str]]]:
        """The other names it reads in the URL: the other languages' of the
        translated ones, of its parameters (``params``, by their key:
        ``view``…), its views (``views``) and its fields of resources
        (``resources``), by their own."""
        kinds = {
            "params": {**URL_PARAMS, **self.calendar_url_params},
            "views": self.calendar_url_views,
            "resources": self.calendar_url_resources,
        }
        return {
            kind: {
                key: others
                for key, name in names.items()
                if (others := translations(name)[1:])
            }
            for kind, names in kinds.items()
        }

    def _url_names(
        self, request: HttpRequest, kind: str, key: str, name: str
    ) -> list[str]:
        """``name`` (``kind``'s ``key``'s), and its other names in the URL."""
        return [name, *self.get_calendar_url_aliases(request)[kind].get(key, [])]

    def _chosen_resources(self, request: HttpRequest) -> tuple[str, str] | None:
        """The URL's choice of the field of its resources, if it's one of
        ``calendar_resource_fields``: its value in the URL, and the field."""
        param = self.get_calendar_url_params(request)["resources"]
        value = next(
            (
                request.GET[name]
                for name in self._url_names(request, "params", "resources", param)
                if request.GET.get(name)
            ),
            "",
        )
        names = {
            other: field
            for field, name in self.get_calendar_url_resources(request).items()
            for other in self._url_names(request, "resources", field, name)
        }
        field = names.get(value, value)
        return (value, field) if field in self.calendar_resource_fields else None

    def _resources_query(self, request: HttpRequest) -> dict[str, str]:
        """The URL's choice of the field of its resources, in the active
        language: for its events' and moves' requests."""
        chosen = self._chosen_resources(request)
        if chosen is None:
            return {}
        field = chosen[1]
        name = self.get_calendar_url_resources(request).get(field, field)
        return {self.get_calendar_url_params(request)["resources"]: name}

    def get_calendar_resource_field(self, request: HttpRequest) -> str | None:
        """The field of its resources: the URL's choice (by its name in it,
        ``get_calendar_url_resources()``, or its own), of
        ``calendar_resource_fields``, else ``calendar_resource_field``."""
        chosen = self._chosen_resources(request)
        return chosen[1] if chosen else self.calendar_resource_field

    def _for_request(self, request: HttpRequest) -> Any:
        """Itself, with the request's field of its resources."""
        name = self.get_calendar_resource_field(request)
        if name == self.calendar_resource_field:
            return self
        calendar = copy.copy(self)
        calendar.calendar_resource_field = name
        return calendar

    def get_calendar_url_views(self, request: HttpRequest) -> dict[str, str]:
        """The views' names in the URL (``calendar_url_views``), in the
        active language."""
        return {view: str(name) for view, name in self.calendar_url_views.items()}

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
        calendar = self._for_request(request)
        if calendar is not self:
            return cast("dict[str, Any]", calendar.get_calendar_initial(request))
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
        calendar = self._for_request(request)
        if calendar is not self:
            return cast("dict[str, Any]", calendar.get_calendar_config(request))
        urls = self.get_calendar_urls(request)
        add = urls.get("add") if self.has_calendar_add_permission(request) else None
        mode = self.get_calendar_move_mode(request)
        movable = self.has_calendar_move_permission(request)
        # Its events and moves of the same field of resources as its page.
        chosen = self._resources_query(request)
        move = _with_query(urls.get("move"), chosen) if movable else None
        moves = (
            _with_query(urls.get("moves"), chosen)
            if movable and mode == "batch"
            else None
        )
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
            params={**self.get_calendar_params(request), **chosen},
            view=self.get_calendar_view(request),
            views=self.get_calendar_views(request),
            add=add,
            move=move,
            moves=moves,
            move_mode=mode if movable else "off",
            undo_seconds=self.get_calendar_undo_seconds(request) if movable else 0,
            dates_only=self.dates_only,
            resources=resources,
            resource=resource,
            url_state=self.get_calendar_url_state(request),
            url_params=self.get_calendar_url_params(request),
            url_views=self.get_calendar_url_views(request),
            url_aliases=self.get_calendar_url_aliases(request),
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
        if self._changed_since(request, obj, move):
            raise CalendarMoveError(
                gettext("It was changed since, so this can't be undone."), 409
            )
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

    def _changed_since(
        self, request: HttpRequest, obj: Model, move: dict[str, Any]
    ) -> bool:
        """Whether ``obj`` is no longer as a move says it should be
        (``expect_start``, ``expect_end`` and ``expect_resources``: what the
        move it undoes left): someone changed it since. Without any of
        them, never."""
        if not any(name.startswith("expect_") for name in move):
            return False
        event = self.get_calendar_event(request, obj)
        current = {
            "expect_start": event.get("start") or "",
            "expect_end": event.get("end") or "",
            "expect_resources": ",".join(
                sorted(str(item) for item in event.get("resourceIds", []))
            ),
        }
        return any(str(move[name]) != current[name] for name in current if name in move)

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
        calendar = self._for_request(request)
        if calendar is not self:
            return cast("JsonResponse", calendar.calendar_events_response(request))
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
        calendar = self._for_request(request)
        if calendar is not self:
            return cast("JsonResponse", calendar.calendar_move_response(request))
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
        calendar = self._for_request(request)
        if calendar is not self:
            return cast("JsonResponse", calendar.calendar_moves_response(request))
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


def _with_query(url: str | None, query: dict[str, str]) -> str | None:
    """``url`` with ``query`` too."""
    if not url or not query:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urlencode(query)}"
