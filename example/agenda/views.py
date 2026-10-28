from django.shortcuts import get_object_or_404, render

from django_event_calendar import EventFeedView

from .models import Booking


class BookingEvents(EventFeedView):
    """The bookings, for the page's calendar (each leads to its page)."""

    queryset = Booking.objects.select_related("room")
    calendar_start_field = "start"
    calendar_end_field = "end"
    calendar_color_field = "color"


def calendar(request):
    return render(request, "agenda/calendar.html")


def booking(request, pk):
    return render(
        request, "agenda/booking.html", {"booking": get_object_or_404(Booking, pk=pk)}
    )
