"""The admin's calendar: a changelist's objects by date — the calendar
(``CalendarMixin``) with the admin's permissions, changelist, saves and
log."""

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
    InlineModelAdmin,
)
from django.contrib.admin.utils import quote
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.forms.models import _get_foreign_key, modelform_factory
from django.http import HttpResponseRedirect, QueryDict
from django.template.loader import select_template
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from .config import calendar_media
from .core import MOVE_MODES, CalendarMixin, CalendarMove, CalendarMoveError
from .source import NO_RESOURCE
from .widget import Calendar

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.contrib.admin.views.main import ChangeList
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest, HttpResponse, JsonResponse
    from django.urls import URLPattern

__all__ = [
    "CALENDAR_PARAMS",
    "MOVE_MODES",
    "RETURN_PARAM",
    "CalendarAdminMixin",
    "CalendarInline",
    "CalendarMove",
    "CalendarMoveError",
]

#: The parameter that takes the calendar's URL to the pages it opens: after
#: a save, back to it.
RETURN_PARAM = "_ec_calendar"

#: What the calendar adds to the changelist's query string: not filters (its
#: range; its view and date, in its page's URL, by default).
CALENDAR_PARAMS = ("start", "end", "timeZone", "ec-view", "ec-date", RETURN_PARAM)


class CalendarAdminMixin(CalendarMixin, BaseModelAdmin):
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
    it. A move is checked by the model (``full_clean()`` of what it
    changes), saved through ``save_model()`` and logged as the admin's
    changes are.

    It's :class:`~django_ec_calendar.CalendarMixin` (its fields, options and
    methods, each taking the request) with the admin's permissions
    (``has_view_or_change_permission()``, ``has_change_permission()``,
    ``has_add_permission()``), changelist, saves and log.
    """

    #: Whether the calendar's page shows the changelist's filters and search.
    calendar_filters = True
    #: The parameter that takes the calendar's URL to the pages it opens:
    #: after a save, back to it.
    calendar_return_param = RETURN_PARAM
    #: The calendar's page.
    calendar_template = "django_ec_calendar/admin/calendar.html"
    #: The changelist's: the admin's, and a link to the calendar.
    calendar_change_list_template = "django_ec_calendar/admin/change_list.html"
    calendar_queryset_errors = (IncorrectLookupParameters,)

    @property
    def uses_calendar(self) -> bool:
        return bool(self.calendar_start_field) and isinstance(self, ModelAdmin)

    def get_source_model(self) -> type[Model]:
        return self.model

    def get_calendar_filters(self, request: HttpRequest) -> bool:
        """Whether its page shows the changelist's filters and search
        (``calendar_filters``)."""
        return self.calendar_filters

    # The admin's permissions -------------------------------------------------

    def has_calendar_view_permission(self, request: HttpRequest) -> bool:
        return bool(self.has_view_or_change_permission(request))

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

    # Its URLs ----------------------------------------------------------------

    def _url_name(self, name: str) -> str:
        opts = self.model._meta
        return f"{opts.app_label}_{opts.model_name}_{name}"

    def _reverse(self, name: str, *args: Any) -> str | None:
        try:
            return reverse(f"{self.admin_site.name}:{self._url_name(name)}", args=args)
        except NoReverseMatch:
            return None

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

    def get_calendar_urls(self, request: HttpRequest) -> dict[str, str | None]:
        return {
            "events": self._reverse("calendar_events"),
            "move": self._reverse("calendar_move"),
            "moves": self._reverse("calendar_moves"),
            "add": self._reverse("add"),
        }

    def get_calendar_params(self, request: HttpRequest) -> dict[str, str]:
        """The changelist's filters and search."""
        filters = self._changelist_request(request).GET
        return {name: str(value) for name, value in filters.items()}

    def get_calendar_return_param(self, request: HttpRequest) -> str | None:
        """``calendar_return_param``."""
        return self.calendar_return_param

    def get_calendar_query_params(self, request: HttpRequest) -> set[str]:
        """What the calendar adds to the changelist's query string: its
        range, its view and date (``get_calendar_url_params()``), and the
        return parameter. Not filters."""
        return {
            "start",
            "end",
            "timeZone",
            *self.get_calendar_url_params(request).values(),
            str(self.get_calendar_return_param(request)),
        }

    def get_calendar_event_url(self, request: HttpRequest, obj: Model) -> str | None:
        """Its change page (read-only, for who may only view it)."""
        if not self.has_view_or_change_permission(request, obj):
            return None
        return self._reverse("change", quote(obj.pk))

    # The changelist's objects ------------------------------------------------

    def _changelist_request(self, request: HttpRequest) -> HttpRequest:
        """The request as the changelist sees it: its filters and search,
        without the calendar's own parameters."""
        changelist = copy.copy(request)
        query = request.GET.copy()
        for name in self.get_calendar_query_params(request):
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

    # The admin's saves -------------------------------------------------------

    def save_calendar_object(
        self, request: HttpRequest, obj: Model, names: list[str]
    ) -> None:
        """Through ``save_model()``."""
        form = modelform_factory(self.model, fields=names)(instance=obj)
        self.save_model(request, obj, form, change=True)  # type: ignore[attr-defined]

    def log_calendar_move(
        self, request: HttpRequest, obj: Model, names: list[str]
    ) -> None:
        """As the admin's changes are."""
        fields = [
            str(getattr(obj._meta.get_field(name), "verbose_name", name))
            for name in names
        ]
        self.log_change(request, obj, [{"changed": {"fields": fields}}])  # type: ignore[attr-defined]

    # Its views ---------------------------------------------------------------

    def calendar_events_view(self, request: HttpRequest) -> JsonResponse:
        return self.calendar_events_response(request)

    def calendar_move_view(self, request: HttpRequest) -> JsonResponse:
        return self.calendar_move_response(request)

    def calendar_moves_view(self, request: HttpRequest) -> JsonResponse:
        return self.calendar_moves_response(request)

    def calendar_page_view(self, request: HttpRequest) -> HttpResponse:
        """The calendar's page: the admin's, with the changelist's links."""
        if not self.has_calendar_view_permission(request):
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

    # Back to the calendar ----------------------------------------------------

    def _calendar_return(self, request: HttpRequest) -> HttpResponseRedirect | None:
        """The calendar the page was opened from (``_ec_calendar``): its page,
        or another of the admin's (an inline's, ``CalendarInline``), to go
        back to it; None: not from it (or not an admin's page)."""
        url = request.GET.get(str(self.get_calendar_return_param(request)), "")
        try:
            admin = reverse(f"{self.admin_site.name}:index")
        except NoReverseMatch:
            admin = None
        if (
            admin
            and url.startswith(admin)
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


class CalendarInline(InlineModelAdmin):
    """An object's calendar, in its change page: the calendar of another
    model's objects related to it, as an inline::

        class AppointmentCalendarInline(CalendarInline):
            model = Appointment  # its admin a CalendarAdminMixin
            fk_name = "professional"  # if it has several to the object


        class ProfessionalAdmin(admin.ModelAdmin):
            inlines = [AppointmentCalendarInline]

    It's the model's admin's calendar (its permissions, business hours,
    moves, details…) of those of the object (filtered by the foreign key, as
    its changelist would be); adding from it, the object is filled in; after
    a save, back to the object's page. It isn't a formset: it neither adds
    nor changes anything with the object's form.
    """

    template = "django_ec_calendar/admin/inline.html"
    extra = 0
    max_num = 0
    can_delete = False
    #: The view it opens on, and those one can switch between (none: those
    #: of the model's admin).
    calendar_view: str | None = None
    calendar_views: Sequence[str] | None = None

    @property
    def media(self) -> Any:
        return super().media + calendar_media()

    def get_calendar_admin(self) -> CalendarAdminMixin:
        """The model's admin, whose calendar it is."""
        model_admin = self.admin_site._registry.get(self.model)
        if not isinstance(model_admin, CalendarAdminMixin) or not (
            model_admin.uses_calendar
        ):
            raise ImproperlyConfigured(
                f"{type(self).__name__}: {self.model.__name__}'s admin isn't a "
                "CalendarAdminMixin with a calendar."
            )
        return model_admin

    def get_calendar_foreign_key(self) -> Any:
        return _get_foreign_key(self.parent_model, self.model, fk_name=self.fk_name)

    # Not a formset: nothing of it in the object's form.

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return super().get_queryset(request).none()

    def get_formset(
        self, request: HttpRequest, obj: Model | None = None, **kwargs: Any
    ) -> Any:
        kwargs["fields"] = []  # No form of its own.
        return super().get_formset(request, obj, **kwargs)

    def has_add_permission(  # type: ignore[override]
        self, request: HttpRequest, obj: Model | None
    ) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Model | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Model | None = None
    ) -> bool:
        return False

    def has_view_permission(
        self, request: HttpRequest, obj: Model | None = None
    ) -> bool:
        """For those who may see the model's admin's calendar."""
        return self.get_calendar_admin().has_calendar_view_permission(request)

    def get_calendar(self, request: HttpRequest, obj: Model | None) -> Calendar | None:
        """The calendar of ``obj``'s; None: it isn't saved yet."""
        if obj is None or obj.pk is None:
            return None
        calendar_admin = self.get_calendar_admin()
        fk = self.get_calendar_foreign_key()
        value = str(getattr(obj, fk.target_field.attname))
        # As its changelist filtered by the object.
        scoped = copy.copy(request)
        query = QueryDict(mutable=True)
        query[f"{fk.name}__{fk.target_field.name}__exact"] = value
        scoped.GET = query  # type: ignore[assignment]
        config = calendar_admin.get_calendar_config(scoped)
        if self.calendar_view:
            config["view"] = self.calendar_view
        if self.calendar_views is not None:
            config["views"] = list(self.calendar_views)
        if config["add"]:
            config["add"] = f"{config['add']}?{fk.name}={value}"
        # Not the object's page's URL: its own.
        config["urlState"] = False
        return Calendar(config, id=f"{self.model._meta.model_name}-calendar")
