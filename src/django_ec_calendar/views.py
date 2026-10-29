"""Calendars on your own pages: ``CalendarView`` (its page and events, and
moving them, as the admin's), and ``EventFeedView`` (only events)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpResponseNotAllowed, JsonResponse
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils.text import capfirst
from django.views.generic.base import View
from django.views.generic.list import MultipleObjectMixin

from .core import CalendarMixin
from .source import CalendarSource

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest, HttpResponse
    from django.urls import URLPattern

    from .widget import Calendar


class EventFeedView(CalendarSource, MultipleObjectMixin, View):
    """The events of a model, as the calendar asks for them
    (``?start=&end=``)::

        class BookingEvents(EventFeedView):
            model = Booking  # or queryset, or get_queryset()
            calendar_start_field = "start"
            calendar_end_field = "end"

    Each event leads to ``get_calendar_event_url()`` (by default its
    ``get_absolute_url()``, when it has one). With
    ``calendar_resource_field``, ``?resources=1`` answers its resources
    (``get_calendar_resources()``): ``{% ec_calendar … resources=True %}``
    asks for them. Who may see them is the view's: ``LoginRequiredMixin``,
    ``get_queryset()``…
    """

    def get_source_model(self) -> type[Model]:
        return self.get_queryset().model

    def get_calendar_event_url(self, obj: Model) -> str | None:
        """Where clicking it leads; None: nowhere."""
        url = getattr(obj, "get_absolute_url", None)
        return url() if callable(url) else None

    def get_calendar_event(self, request: HttpRequest, obj: Model) -> dict[str, Any]:
        event = super().get_calendar_event(request, obj)
        url = self.get_calendar_event_url(obj)
        if url:
            event.setdefault("extendedProps", {})["url"] = url
        return event

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        if self.calendar_resource_field and request.GET.get("resources"):
            return JsonResponse(self.get_calendar_resources(request), safe=False)
        return JsonResponse(
            self.get_calendar_events(request, self.get_queryset()), safe=False
        )


class CalendarView(CalendarMixin, View):
    """A calendar on your own pages, as the admin's: its events, clicking
    one, adding with the dates selected, moving them as
    ``calendar_move_mode`` says, business hours, resources::

        class ProfessionalAgenda(CalendarView):
            calendar_start_field = "start"
            calendar_duration_field = "minutes"
            calendar_move_mode = "confirm"
            calendar_add_url = "appointment-add"  # a URL's name, or a path

            def get_queryset(self):
                return Appointment.objects.filter(professional=self.kwargs["pk"])

        urlpatterns = [
            path("agenda/<int:pk>/", include(ProfessionalAgenda.urls("agenda"))),
        ]

    ``urls(name)`` are its page (``name``) and its events, move and moves
    (``name-events``, ``name-move``, ``name-moves``), under the same path.
    Its page is ``template_name`` with ``calendar`` (``{{ calendar.media
    }}``, ``{{ calendar }}``) and ``title``; ``calendar_for()`` is the
    calendar for any other page.

    Who may do what is the user's model permissions, by default
    (``has_calendar_view_permission()``…); what it shows is
    ``get_queryset()``. A move is saved with ``obj.save()``
    (``save_calendar_object()``).
    """

    #: Its objects: the model's, or a queryset's (or ``get_queryset()``).
    model: type[Model] | None = None
    queryset: QuerySet[Any] | None = None
    #: Its page.
    template_name = "django_ec_calendar/page.html"
    #: Its page's title (none: the model's plural name).
    title: str | None = None
    #: The add page (a URL's name, or a path), which gets the dates as
    #: ``?start=&end=`` (``get_calendar_initial()``, for its form); none: no
    #: adding.
    calendar_add_url: str | None = None
    #: Where its page is, for its endpoints (none: the request's, on its
    #: page).
    calendar_base_url: str | None = None
    #: What this view answers: its page, its events, a move or several
    #: (``urls()`` sets it).
    action = "page"

    @classmethod
    def urls(cls, name: str = "calendar", **initkwargs: Any) -> list[URLPattern]:
        """Its page (``name``), and its endpoints under it."""
        return [
            path("", cls.as_view(action="page", **initkwargs), name=name),
            path(
                "events/",
                cls.as_view(action="events", **initkwargs),
                name=f"{name}-events",
            ),
            path(
                "move/",
                cls.as_view(action="move", **initkwargs),
                name=f"{name}-move",
            ),
            path(
                "moves/",
                cls.as_view(action="moves", **initkwargs),
                name=f"{name}-moves",
            ),
        ]

    @classmethod
    def calendar_for(
        cls, request: HttpRequest, url: str, *args: Any, **kwargs: Any
    ) -> Calendar:
        """Its calendar, for another page: ``url`` is its page's (where its
        endpoints are, under it); ``args``/``kwargs``, its URL's."""
        view = cls()
        view.setup(request, *args, **kwargs)
        view.calendar_base_url = url
        return view.get_calendar(request)

    def get_queryset(self) -> QuerySet[Any]:
        if self.queryset is not None:
            return self.queryset.all()
        if self.model is not None:
            return self.model._default_manager.all()
        raise ImproperlyConfigured(
            f"{type(self).__name__} needs a model, a queryset or get_queryset()."
        )

    def get_source_model(self) -> type[Model]:
        return self.model or self.get_queryset().model

    def get_calendar_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return self.get_queryset()

    def get_calendar_base_url(self, request: HttpRequest) -> str:
        url = self.calendar_base_url or request.path
        return url if url.endswith("/") else f"{url}/"

    def get_calendar_add_url(self, request: HttpRequest) -> str | None:
        """``calendar_add_url``: a URL's name, or a path."""
        url = self.calendar_add_url
        if not url:
            return None
        try:
            return reverse(url)
        except NoReverseMatch:
            return url

    def get_calendar_urls(self, request: HttpRequest) -> dict[str, str | None]:
        base = self.get_calendar_base_url(request)
        return {
            "events": f"{base}events/",
            "move": f"{base}move/",
            "moves": f"{base}moves/",
            "add": self.get_calendar_add_url(request),
        }

    def has_calendar_add_permission(self, request: HttpRequest) -> bool:
        return bool(
            self.get_calendar_add_url(request)
            and super().has_calendar_add_permission(request)
        )

    def get_title(self) -> str:
        if self.title is not None:
            return self.title
        return capfirst(str(self.get_source_model()._meta.verbose_name_plural))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "view": self,
            "title": self.get_title(),
            "calendar": self.get_calendar(self.request),
            **kwargs,
        }

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if self.action == "events":
            return self.calendar_events_response(request)
        if self.action != "page":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_calendar_view_permission(request):
            raise PermissionDenied
        return TemplateResponse(request, self.template_name, self.get_context_data())

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if self.action == "move":
            return self.calendar_move_response(request)
        if self.action == "moves":
            return self.calendar_moves_response(request)
        return HttpResponseNotAllowed(["GET"])
