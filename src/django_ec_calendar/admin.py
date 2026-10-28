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
from django.http import JsonResponse
from django.template.loader import select_template
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from .config import calendar_config, calendar_media
from .source import CalendarSource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.contrib.admin.views.main import ChangeList
    from django.db.models import Model
    from django.http import HttpRequest, HttpResponse
    from django.urls import URLPattern

#: What the calendar adds to the changelist's query string: not filters.
CALENDAR_PARAMS = ("start", "end", "timeZone")


class CalendarAdminMixin(CalendarSource, BaseModelAdmin):
    """``ModelAdmin`` mixin: a calendar of the changelist's objects, a click
    away from it ("Calendar")::

        class BookingAdmin(CalendarAdminMixin, admin.ModelAdmin):
            calendar_start_field = "start"
            calendar_end_field = "end"  # optional

    It shows what the changelist would (its ``get_queryset()``, filters and
    search), a month at a time by default. Clicking an event opens its
    change page; selecting dates opens the add page with them (for those
    who may add); dragging an event, or its end, saves its dates (for those
    who may change it: ``calendar_editable``). A move is checked by the
    model (``full_clean()`` of its dates), saved through ``save_model()``
    and logged as the admin's changes are.

    The fields, as :class:`~django_ec_calendar.CalendarSource`'s
    (``calendar_start_field``, ``calendar_end_field``,
    ``calendar_all_day_field``, ``calendar_title_field``,
    ``calendar_color_field``); ``calendar_view`` and ``calendar_views``,
    which views; ``calendar_options``, any other of EventCalendar's.
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
    #: Whether dragging an event (or its end) saves its dates.
    calendar_editable = True
    #: Whether selecting dates opens the add page with them.
    calendar_selectable = True
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
        if not self.calendar_end_field:
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

    def calendar_events_view(self, request: HttpRequest) -> JsonResponse:
        """The events of ``?start=&end=``, of the changelist's objects (its
        filters and search, in the rest of the query string)."""
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        changelist_request = self._changelist_request(request)
        try:
            cl = cast(
                "ChangeList",
                self.get_changelist_instance(changelist_request),  # type: ignore[attr-defined]
            )
        except IncorrectLookupParameters:
            return JsonResponse({"error": gettext("Unknown filter.")}, status=400)
        queryset = cl.get_queryset(changelist_request)
        return JsonResponse(self.get_calendar_events(request, queryset), safe=False)

    def calendar_move_view(self, request: HttpRequest) -> JsonResponse:
        """An event dragged, or its end: ``pk``, ``start`` and ``end`` (as
        the calendar sends them)."""
        try:
            obj = self.get_queryset(request).filter(pk=request.POST.get("pk")).first()
        except (ValueError, TypeError, ValidationError):
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
        for name, value in values.items():
            setattr(obj, name, value)
        try:
            # Its dates as the model checks them (and its clean()).
            obj.full_clean(
                exclude=[
                    field.name for field in obj._meta.fields if field.name not in values
                ],
                validate_unique=False,
            )
        except ValidationError as error:
            return JsonResponse({"error": " ".join(error.messages)}, status=400)
        form = modelform_factory(self.model, fields=list(values))(instance=obj)
        self.save_model(request, obj, form, change=True)  # type: ignore[attr-defined]
        fields = [str(obj._meta.get_field(name).verbose_name) for name in values]
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
        return calendar_config(
            request,
            events=cast("str", self._reverse("calendar_events")),
            params={name: str(value) for name, value in filters.items()},
            view=self.calendar_view,
            views=self.calendar_views,
            add=add,
            move=move,
            dates_only=self.dates_only,
            options=self.calendar_options,
        )

    def calendar_page_view(self, request: HttpRequest) -> HttpResponse:
        """The calendar's page: the admin's, with the changelist's links."""
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        opts = self.model._meta
        filters = self._changelist_request(request).GET
        changelist = cast("str", self._reverse("changelist"))
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
            "unfold": apps.is_installed("unfold"),
            # Django 6's breadcrumbs are a list; before, links and "›".
            "breadcrumbs_list": django.VERSION >= (6, 0),
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
            for name in (self.calendar_start_field, self.calendar_end_field):
                if name and isinstance(initial.get(name), str):
                    del initial[name]
            values = self.moved_values(request.GET.get("start"), request.GET.get("end"))
            if values:
                initial.update(
                    {name: value for name, value in values.items() if value is not None}
                )
        return cast("dict[str, Any]", initial)
