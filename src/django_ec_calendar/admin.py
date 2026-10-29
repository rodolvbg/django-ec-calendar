"""The admin's calendar: a changelist's objects by date."""

from __future__ import annotations

import copy
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
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms.models import modelform_factory
from django.http import HttpResponseRedirect, JsonResponse
from django.template.loader import select_template
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from .config import calendar_config, calendar_media
from .source import NO_RESOURCE, CalendarSource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.contrib.admin.views.main import ChangeList
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest, HttpResponse
    from django.urls import URLPattern

#: The parameter that takes the calendar's URL to the pages it opens: after
#: a save, back to it.
RETURN_PARAM = "_ec_calendar"
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
    URL). With ``calendar_editable``, dragging an event, or its end, saves
    its dates (and its resource), asking first (``calendar_confirm_move``),
    for those who may change it. A move is checked by the model
    (``full_clean()`` of what it changes), saved through ``save_model()``
    and logged as the admin's changes are.

    The fields, as :class:`~django_ec_calendar.CalendarSource`'s
    (``calendar_start_field``, ``calendar_end_field`` or
    ``calendar_duration_field``, ``calendar_all_day_field``,
    ``calendar_title_field``, ``calendar_color_field``,
    ``calendar_detail_fields``, ``calendar_resource_field``);
    ``calendar_view`` and ``calendar_views``, which views;
    ``calendar_options``, any other of EventCalendar's.
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
    #: Whether dragging an event (or its end) saves its dates: off by default
    #: (a slip of the mouse would change one).
    calendar_editable = False
    #: Whether a move asks first.
    calendar_confirm_move = True
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
        event["editable"] = bool(
            self.calendar_editable and self.has_change_permission(request, obj)
        )
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

    def calendar_move_view(self, request: HttpRequest) -> JsonResponse:
        """An event dragged, or its end: ``pk``, ``start`` and ``end`` (as
        the calendar sends them); to another resource, ``resource`` (and
        ``resource_from``, the one it was dragged from)."""
        try:
            obj = (
                self.get_calendar_queryset(request)
                .filter(pk=request.POST.get("pk"))
                .first()
            )
        except (ValueError, TypeError, ValidationError, IncorrectLookupParameters):
            obj = None
        if obj is None:
            return JsonResponse(
                {"error": gettext("It doesn't exist any more.")}, status=404
            )
        if not (self.calendar_editable and self.has_change_permission(request, obj)):
            raise PermissionDenied
        values = self.moved_values(request.POST.get("start"), request.POST.get("end"))
        if values is None:
            return JsonResponse({"error": gettext("Not a date.")}, status=400)
        names = list(values)
        many: tuple[str, str] | None = None
        resource = request.POST.get("resource")
        if resource is not None and self.calendar_resource_field:
            field = self._field(self.calendar_resource_field)
            if not (self.calendar_resource_editable and field.editable):
                message = gettext("It can't be moved to another %(name)s.")
                return JsonResponse(
                    {"error": message % {"name": field.verbose_name}}, status=400
                )
            if resource not in {
                item["id"] for item in self.get_calendar_resources(request)
            }:
                message = gettext("Unknown %(name)s.")
                return JsonResponse(
                    {"error": message % {"name": field.verbose_name}}, status=400
                )
            if self._resource_kind() == "many":
                many = (request.POST.get("resource_from", NO_RESOURCE), resource)
            else:
                values[field.attname] = self.resource_value(resource)
                names.append(field.name)
        for name, value in values.items():
            setattr(obj, name, value)
        try:
            # What it changes as the model checks it (and its clean()).
            obj.full_clean(
                exclude=[
                    field.name for field in obj._meta.fields if field.name not in names
                ],
                validate_unique=False,
            )
        except ValidationError as error:
            return JsonResponse({"error": " ".join(error.messages)}, status=400)
        form = modelform_factory(self.model, fields=names)(instance=obj)
        self.save_model(request, obj, form, change=True)  # type: ignore[attr-defined]
        if many:
            related = getattr(obj, cast("str", self.calendar_resource_field))
            old, new = many
            if old != NO_RESOURCE:
                related.remove(self.resource_value(old))
            if new != NO_RESOURCE:
                related.add(self.resource_value(new))
            names.append(cast("str", self.calendar_resource_field))
        fields = [str(obj._meta.get_field(name).verbose_name) for name in names]
        self.log_change(request, obj, [{"changed": {"fields": fields}}])  # type: ignore[attr-defined]
        return JsonResponse({"event": self.get_calendar_event(request, obj)})

    # The pages ----------------------------------------------------------------

    def get_calendar_config(self, request: HttpRequest) -> dict[str, Any]:
        """The calendar's configuration, for its script."""
        filters = self._changelist_request(request).GET
        add = None
        if self.calendar_selectable and self.has_add_permission(request):
            add = self._reverse("add")
        move = None
        if self.calendar_editable and self.has_change_permission(request):
            move = self._reverse("calendar_move")
        resources = resource = None
        if self.calendar_resource_field:
            field = self._field(self.calendar_resource_field)
            resources = self.get_calendar_resources(request)
            message = gettext("It can't be moved to another %(name)s.")
            resource = {
                "param": field.name,
                "empty": NO_RESOURCE,
                "editable": bool(self.calendar_resource_editable and field.editable),
                "message": message % {"name": field.verbose_name},
            }
        return calendar_config(
            request,
            events=cast("str", self._reverse("calendar_events")),
            params={name: str(value) for name, value in filters.items()},
            view=self.calendar_view,
            views=self.calendar_views,
            add=add,
            move=move,
            dates_only=self.dates_only,
            resources=resources,
            resource=resource,
            url_state=self.calendar_url_state,
            highlight_today=self.calendar_highlight_today,
            confirm_move=self.calendar_confirm_move,
            return_param=RETURN_PARAM,
            options=self.calendar_options,
        )

    def calendar_page_view(self, request: HttpRequest) -> HttpResponse:
        """The calendar's page: the admin's, with the changelist's links."""
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        opts = self.model._meta
        filters = self._changelist_request(request).GET
        changelist = cast("str", self._reverse("changelist"))
        cl = None
        if self.calendar_filters:
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
