"""A calendar's events for your own pages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.http import JsonResponse
from django.views.generic.base import View
from django.views.generic.list import MultipleObjectMixin

from .source import CalendarSource

if TYPE_CHECKING:
    from django.db.models import Model
    from django.http import HttpRequest


class EventFeedView(CalendarSource, MultipleObjectMixin, View):
    """The events of a model, as the calendar asks for them
    (``?start=&end=``)::

        class BookingEvents(EventFeedView):
            model = Booking  # or queryset, or get_queryset()
            calendar_start_field = "start"
            calendar_end_field = "end"

    Each event leads to ``get_calendar_event_url()`` (by default its
    ``get_absolute_url()``, when it has one). Who may see them is the
    view's: ``LoginRequiredMixin``, ``get_queryset()``…
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
        return JsonResponse(
            self.get_calendar_events(request, self.get_queryset()), safe=False
        )
