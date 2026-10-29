from django.shortcuts import get_object_or_404, render

from django_ec_calendar import CalendarView, EventFeedView

from .models import Appointment, Booking, Professional


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


class ProfessionalAgenda(CalendarView):
    """A professional's agenda, on a page of its own (not the admin's): their
    appointments, moved asking first, added on the admin's add page."""

    calendar_start_field = "start"
    calendar_duration_field = "minutes"
    calendar_detail_fields = ("get_status_display",)
    calendar_view = "timeGridWeek"
    calendar_views = ("timeGridWeek", "timeGridDay", "listWeek")
    calendar_move_mode = "confirm"
    calendar_add_url = "admin:agenda_appointment_add"
    calendar_options = {"slotMinTime": "08:00", "slotMaxTime": "20:00"}

    def get_queryset(self):
        return Appointment.objects.filter(professional=self.kwargs["pk"])

    def get_title(self):
        return f"Agenda: {get_object_or_404(Professional, pk=self.kwargs['pk'])}"
