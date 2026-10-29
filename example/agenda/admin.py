from django.contrib import admin

from django_ec_calendar import CalendarAdminMixin, CalendarInline
from django_ec_calendar.source import ONE_DAY

from .models import Appointment, Booking, Holiday, Professional, Room

#: The professionals with hours of their own (the rest: the calendar's).
PROFESSIONAL_HOURS = {
    "Ana": {"start": "09:00", "end": "14:00"},
    "Luis": {"start": "16:00", "end": "20:00"},
}


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "color")


@admin.register(Booking)
class BookingAdmin(CalendarAdminMixin, admin.ModelAdmin):
    list_display = ("title", "room", "start", "end")
    list_filter = ("room",)
    list_select_related = ("room",)
    search_fields = ("title",)
    # "Calendar", next to "Add": the bookings by date, in their room's color.
    calendar_start_field = "start"
    calendar_end_field = "end"
    calendar_color_field = "color"
    calendar_view = "timeGridWeek"
    calendar_options = {"slotMinTime": "07:00", "slotMaxTime": "21:00"}
    # Dragging saves, asking first.
    calendar_move_mode = "confirm"


@admin.register(Holiday)
class HolidayAdmin(CalendarAdminMixin, admin.ModelAdmin):
    list_display = ("name", "first_day", "last_day")
    # Whole days (DateField): all-day events.
    calendar_start_field = "first_day"
    calendar_end_field = "last_day"
    calendar_views = ("dayGridMonth", "listYear")


class AppointmentCalendarInline(CalendarInline):
    """A professional's appointments, in their page: the appointments'
    calendar (its hours, moves…), of theirs."""

    model = Appointment
    calendar_view = "timeGridWeek"
    calendar_views = ("timeGridWeek", "timeGridDay", "listWeek")


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    list_display = ("name", "active")
    inlines = [AppointmentCalendarInline]


@admin.register(Appointment)
class AppointmentAdmin(CalendarAdminMixin, admin.ModelAdmin):
    list_display = ("client", "professional", "start", "minutes", "status")
    list_filter = ("professional", "status")
    list_select_related = ("professional",)
    search_fields = ("client",)
    # A column per (active) professional, and one for those of nobody yet.
    calendar_start_field = "start"
    calendar_duration_field = "minutes"
    calendar_resource_field = "professional"
    calendar_detail_fields = ("get_status_display",)
    calendar_view = "resourceTimeGridDay"
    calendar_views = ("resourceTimeGridDay", "resourceTimeGridWeek", "listWeek")
    # Several moved, then saved together.
    calendar_move_mode = "batch"

    # Weekdays, 9 to 14 and 16 to 20: the rest shaded, and not to be booked.
    calendar_business_hours = [
        {"days": [1, 2, 3, 4, 5], "start": "09:00", "end": "14:00"},
        {"days": [1, 2, 3, 4, 5], "start": "16:00", "end": "20:00"},
    ]
    calendar_outside_hours = "block"

    def get_calendar_business_hours(self, request, resource=None):
        # Each professional's own: Ana in the mornings, Luis in the afternoons.
        name = PROFESSIONAL_HOURS.get(self._professional(resource))
        if name:
            return [{"days": [1, 2, 3, 4, 5], **name}]
        return super().get_calendar_business_hours(request, resource)

    def _professional(self, resource):
        professional = (
            Professional.objects.filter(pk=resource).first()
            if resource and resource.isdigit()
            else None
        )
        return professional.name if professional else None

    def get_calendar_closed(self, request, start, end, resource=None):
        # The holidays: closed, all day.
        return [
            (holiday.first_day, (holiday.last_day or holiday.first_day) + ONE_DAY)
            for holiday in Holiday.objects.filter(first_day__lt=end)
            if (holiday.last_day or holiday.first_day) >= start
        ]

    def get_calendar_queryset(self, request):
        # The calendar only: not the cancelled ones.
        return super().get_calendar_queryset(request).exclude(status="cancelled")
