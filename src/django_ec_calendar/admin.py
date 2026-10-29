"""The admin's calendar: a changelist's objects by date."""

from __future__ import annotations

import copy
import dataclasses
import json
from typing import TYPE_CHECKING, Any, cast

import django
from django.apps import apps
from django.contrib.admin import ModelAdmin
from django.contrib.admin.options import (
    IS_POPUP_VAR,
    BaseModelAdmin,
    IncorrectLookupParameters,
)
from django.contrib.admin.utils import quote
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db import transaction
from django.forms.models import modelform_factory
from django.http import HttpResponseRedirect, JsonResponse
from django.template.loader import select_template
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from .config import calendar_config, calendar_media
from .source import NO_RESOURCE, ONE_DAY, CalendarSource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.contrib.admin.views.main import ChangeList
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest, HttpResponse
    from django.urls import URLPattern

#: The parameter that takes the calendar's URL to the pages it opens: after
#: a save, back to it.
RETURN_PARAM = "_ec_calendar"
#: How dragging an event (or its end) goes: not at all, saved at once,
#: asked first, or kept until several are saved together.
MOVE_MODES = ("off", "save", "confirm", "batch")

#: What the calendar adds to the changelist's query string: not filters (its
#: range; its view and date, in its page's URL).
CALENDAR_PARAMS = ("start", "end", "timeZone", "ec-view", "ec-date", RETURN_PARAM)


class CalendarAdminMixin(CalendarSource, BaseModelAdmin):
    """``ModelAdmin`` mixin: a calendar of the changelist's objects, a click
    away from it ("Calendar")::

        class BookingAdmin(CalendarAdminMixin, admin.ModelAdmin):
            calendar_start_field = "start"
            calendar_end_field = "end"  # optional

    It shows what the changelist would (``get_calendar_queryset()``: its
    queryset, filters and search, which it shows above it too), a month at a
    time by default. Clicking an event opens its change page; selecting
    dates opens the add page with them (for those who may add); after a
    save, back to the calendar, where it was (its view and date are in its
    URL). Dragging an event, or its end, changes its dates (and its
    resource), as ``calendar_move_mode`` says (off by default; saved at
    once, asked first, or several saved together), for those who may change
    it. A move is checked by the model
    (``full_clean()`` of what it changes), saved through ``save_model()``
    and logged as the admin's changes are.

    The fields, as :class:`~django_ec_calendar.CalendarSource`'s
    (``calendar_start_field``, ``calendar_end_field`` or
    ``calendar_duration_field``, ``calendar_all_day_field``,
    ``calendar_title_field``, ``calendar_color_field``,
    ``calendar_detail_fields``, ``calendar_resource_field``);
    ``calendar_view`` and ``calendar_views``, which views;
    ``calendar_options``, any other of EventCalendar's;
    ``calendar_business_hours`` (and ``get_calendar_closed()``), when it's
    open.

    Each option has its method, which takes the request (as the admin's
    ``get_list_display()``): ``get_calendar_view()``,
    ``get_calendar_views()``, ``get_calendar_detail_fields()``,
    ``get_calendar_business_hours()``…; who may move an event, or add one
    from the calendar, is ``has_calendar_move_permission()`` and
    ``has_calendar_add_permission()``.
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
    #: Whether the calendar's page shows the changelist's filters and search.
    calendar_filters = True
    #: Whether its view and date go in its page's URL (``ec-view``,
    #: ``ec-date``): one comes back to the same place, and can share it.
    calendar_url_state = True
    #: Whether today is tinted (never in a day's view).
    calendar_highlight_today = True
    #: Any other of EventCalendar's options (JSON).
    calendar_options: dict[str, Any] = {}  # noqa: RUF012
    #: The calendar's page.
    calendar_template = "django_ec_calendar/admin/calendar.html"
    #: The changelist's: the admin's, and a link to the calendar.
    calendar_change_list_template = "django_ec_calendar/admin/change_list.html"

    @property
    def uses_calendar(self) -> bool:
        return bool(self.calendar_start_field) and isinstance(self, ModelAdmin)

    def get_source_model(self) -> type[Model]:
        return self.model

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

    def get_calendar_filters(self, request: HttpRequest) -> bool:
        """Whether its page shows the changelist's filters and search
        (``calendar_filters``)."""
        return self.calendar_filters

    def get_calendar_url_state(self, request: HttpRequest) -> bool:
        """Whether its view and date go in its page's URL
        (``calendar_url_state``)."""
        return self.calendar_url_state

    def get_calendar_highlight_today(self, request: HttpRequest) -> bool:
        """Whether today is tinted (``calendar_highlight_today``)."""
        return self.calendar_highlight_today

    def get_calendar_options(self, request: HttpRequest) -> dict[str, Any]:
        """Any other of EventCalendar's options (``calendar_options``): what
        the calendar shows, not what the server allows (that has its own
        methods). Over those fitted to the business hours."""
        return dict(self.calendar_options)

    def has_calendar_move_permission(
        self, request: HttpRequest, obj: Model | None = None
    ) -> bool:
        """Whether one may drag ``obj`` (none: any event) to change it: its
        mode isn't ``"off"``, and one may change it."""
        return bool(
            self.get_calendar_move_mode(request) != "off"
            and self.has_change_permission(request, obj)
        )

    def has_calendar_add_permission(self, request: HttpRequest) -> bool:
        """Whether selecting dates opens the add page with them:
        ``calendar_selectable``, and one may add."""
        return bool(self.calendar_selectable and self.has_add_permission(request))

    def _url_name(self, name: str) -> str:
        opts = self.model._meta
        return f"{opts.app_label}_{opts.model_name}_{name}"

    def _reverse(self, name: str, *args: Any) -> str | None:
        try:
            return reverse(f"{self.admin_site.name}:{self._url_name(name)}", args=args)
        except NoReverseMatch:
            return None

    # The URLs -----------------------------------------------------------------

    def get_urls(self) -> list[URLPattern]:
        urls = super().get_urls()  # type: ignore[misc]
        if not self.uses_calendar:
            return urls
        wrap = self.admin_site.admin_view
        return [
            path(
                "calendar/",
                wrap(self.calendar_page_view),
                name=self._url_name("calendar"),
            ),
            path(
                "calendar/events/",
                wrap(self.calendar_events_view),
                name=self._url_name("calendar_events"),
            ),
            path(
                "calendar/move/",
                wrap(require_POST(self.calendar_move_view)),
                name=self._url_name("calendar_move"),
            ),
            path(
                "calendar/moves/",
                wrap(require_POST(self.calendar_moves_view)),
                name=self._url_name("calendar_moves"),
            ),
            *urls,
        ]

    # The events ---------------------------------------------------------------

    def get_calendar_event(self, request: HttpRequest, obj: Model) -> dict[str, Any]:
        """An event, with where clicking it leads (its change page) and
        whether it may be dragged (one may change it)."""
        event = super().get_calendar_event(request, obj)
        url = (
            self._reverse("change", quote(obj.pk))
            if self.has_view_or_change_permission(request, obj)
            else None
        )
        if url:
            event.setdefault("extendedProps", {})["url"] = url
        event["editable"] = self.has_calendar_move_permission(request, obj)
        if not self.has_end:
            event["durationEditable"] = False  # No end to change.
        return event

    def _changelist_request(self, request: HttpRequest) -> HttpRequest:
        """The request as the changelist sees it: its filters and search,
        without the calendar's own parameters."""
        changelist = copy.copy(request)
        query = request.GET.copy()
        for name in CALENDAR_PARAMS:
            query.pop(name, None)
        changelist.GET = query  # type: ignore[assignment]
        return changelist

    def get_calendar_changelist(self, request: HttpRequest) -> ChangeList:
        """The changelist of the calendar's filters and search (the rest of
        its query string). Raises ``IncorrectLookupParameters``, as the
        changelist does, for a filter it doesn't know."""
        return cast(
            "ChangeList",
            self.get_changelist_instance(self._changelist_request(request)),  # type: ignore[attr-defined]
        )

    def get_calendar_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        """What the calendar shows: the changelist's objects, with its
        filters and search. Override it (calling ``super()``) to restrict
        the calendar only."""
        return self.get_calendar_changelist(request).get_queryset(
            self._changelist_request(request)
        )

    def get_calendar_resources(self, request: HttpRequest) -> list[dict[str, Any]]:
        """The resources; with the changelist filtering by one (or by none:
        ``__isnull``), only those."""
        resources = super().get_calendar_resources(request)
        query = self._changelist_request(request).GET
        name = cast("str", self.calendar_resource_field)
        field = self._field(name)
        keys = [name, f"{name}__exact", f"{name}__in"]
        if field.is_relation:
            keys += [f"{name}__{field.target_field.name}__exact", f"{name}__pk__exact"]
        chosen: set[str] = set()
        for key in keys:
            for value in query.getlist(key):
                chosen.update(value.split(",") if key.endswith("__in") else [value])
        if query.get(f"{name}__isnull") in ("True", "true", "1"):
            chosen.add(NO_RESOURCE)
        if chosen:
            resources = [item for item in resources if item["id"] in chosen]
        return resources

    def calendar_events_view(self, request: HttpRequest) -> JsonResponse:
        """The events of ``?start=&end=``, of ``get_calendar_queryset()``
        (the changelist's filters and search, in the rest of the query
        string)."""
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        try:
            queryset = self.get_calendar_queryset(request)
        except IncorrectLookupParameters:
            return JsonResponse({"error": gettext("Unknown filter.")}, status=400)
        return JsonResponse(self.get_calendar_events(request, queryset), safe=False)

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

    def save_calendar_move(self, request: HttpRequest, move: CalendarMove) -> None:
        """A move checked by ``prepare_calendar_move()``, saved through
        ``save_model()`` and logged as the admin's changes are."""
        obj, names = move.obj, list(move.names)
        form = modelform_factory(self.model, fields=move.names)(instance=obj)
        self.save_model(request, obj, form, change=True)  # type: ignore[attr-defined]
        if move.many:
            related = getattr(obj, cast("str", self.calendar_resource_field))
            old, new = move.many
            if old != NO_RESOURCE:
                related.remove(self.resource_value(old))
            if new != NO_RESOURCE:
                related.add(self.resource_value(new))
            names.append(cast("str", self.calendar_resource_field))
        fields = [str(obj._meta.get_field(name).verbose_name) for name in names]
        self.log_change(request, obj, [{"changed": {"fields": fields}}])  # type: ignore[attr-defined]

    def calendar_move_view(self, request: HttpRequest) -> JsonResponse:
        """An event dragged, or its end: ``pk``, ``start`` and ``end`` (as
        the calendar sends them); to another resource, ``resource`` (and
        ``resource_from``, the one it was dragged from)."""
        try:
            move = self.prepare_calendar_move(request, request.POST.dict())
        except IncorrectLookupParameters:
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

    def calendar_moves_view(self, request: HttpRequest) -> JsonResponse:
        """Several moves, saved together (``"batch"``): a JSON body,
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
        except IncorrectLookupParameters:
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

    # The pages ----------------------------------------------------------------

    def get_calendar_config(self, request: HttpRequest) -> dict[str, Any]:
        """The calendar's configuration, for its script."""
        filters = self._changelist_request(request).GET
        add = (
            self._reverse("add") if self.has_calendar_add_permission(request) else None
        )
        mode = self.get_calendar_move_mode(request)
        movable = self.has_calendar_move_permission(request)
        move = self._reverse("calendar_move") if movable else None
        moves = self._reverse("calendar_moves") if movable and mode == "batch" else None
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
            events=cast("str", self._reverse("calendar_events")),
            params={name: str(value) for name, value in filters.items()},
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
            highlight_today=self.get_calendar_highlight_today(request),
            outside_hours=self.calendar_outside_hours,
            return_param=RETURN_PARAM,
            # Fitted to the business hours, unless its own options say.
            options={
                **self.get_calendar_hours_options(request),
                **self.get_calendar_options(request),
            },
        )

    def calendar_page_view(self, request: HttpRequest) -> HttpResponse:
        """The calendar's page: the admin's, with the changelist's links."""
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        opts = self.model._meta
        filters = self._changelist_request(request).GET
        changelist = cast("str", self._reverse("changelist"))
        cl = None
        if self.get_calendar_filters(request):
            try:
                cl = self.get_calendar_changelist(request)
            except IncorrectLookupParameters:
                cl = None  # The events say so.
        context = {
            **self.admin_site.each_context(request),
            "opts": opts,
            "title": gettext("Calendar of %(name)s")
            % {"name": opts.verbose_name_plural},
            "calendar": self.get_calendar_config(request),
            "changelist_url": f"{changelist}?{filters.urlencode()}"
            if filters
            else changelist,
            "has_add_permission": self.has_add_permission(request),
            # The changelist's filters and search, above the calendar.
            "cl": cl,
            "unfold": apps.is_installed("unfold"),
            # Django 6's breadcrumbs are a list (before, links and "›"), and
            # its changelist's filters are next to the content (before,
            # after its container).
            "django_6": django.VERSION >= (6, 0),
            "media": self.media + calendar_media(),
        }
        return TemplateResponse(request, self.calendar_template, context)

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        """The changelist, with a link to the calendar (of its filters)."""
        response = super().changelist_view(request, extra_context)  # type: ignore[misc]
        if (
            not self.uses_calendar
            or IS_POPUP_VAR in request.GET
            or not isinstance(response, TemplateResponse)
            or response.is_rendered
        ):
            return response
        context = response.context_data or {}
        url = self._reverse("calendar")
        if url and request.GET:
            url = f"{url}?{request.GET.urlencode()}"
        # The admin's changelist_view() renders a name or a list of names.
        template_name = cast("str | Sequence[str]", response.template_name)
        context["django_ec_calendar_parent"] = select_template(
            [template_name] if isinstance(template_name, str) else template_name
        )
        context["django_ec_calendar_url"] = url
        context["django_ec_calendar_unfold"] = apps.is_installed("unfold")
        response.template_name = self.calendar_change_list_template
        return response

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        """The add page from the calendar (``?start=&end=``): those dates in
        their fields, as the fields take them."""
        initial = super().get_changeform_initial_data(request)  # type: ignore[misc]
        if self.uses_calendar and "start" in request.GET:
            # Not the calendar's text in a field (a field named "start").
            for name in (
                self.calendar_start_field,
                self.calendar_end_field,
                self.calendar_duration_field,
            ):
                if name and isinstance(initial.get(name), str):
                    del initial[name]
            values = self.moved_values(request.GET.get("start"), request.GET.get("end"))
            if values:
                initial.update(
                    {name: value for name, value in values.items() if value is not None}
                )
        return cast("dict[str, Any]", initial)

    # Back to the calendar --------------------------------------------------------

    def _calendar_return(self, request: HttpRequest) -> HttpResponseRedirect | None:
        """The calendar the page was opened from (``_ec_calendar``), to go
        back to it; None: not from it (or not this calendar's URL)."""
        url = request.GET.get(RETURN_PARAM, "")
        calendar = self._reverse("calendar")
        if (
            calendar
            and url.startswith(calendar)
            and url_has_allowed_host_and_scheme(
                url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            )
        ):
            return HttpResponseRedirect(url)
        return None

    def response_post_save_add(
        self, request: HttpRequest, obj: Model
    ) -> HttpResponseRedirect:
        """Added from the calendar: back to it."""
        back = self._calendar_return(request)
        return back or super().response_post_save_add(request, obj)  # type: ignore[misc]

    def response_post_save_change(
        self, request: HttpRequest, obj: Model
    ) -> HttpResponseRedirect:
        """Changed from the calendar: back to it."""
        back = self._calendar_return(request)
        return back or super().response_post_save_change(request, obj)  # type: ignore[misc]


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
