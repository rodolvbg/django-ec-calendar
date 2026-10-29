from django.contrib import admin

from django_ec_calendar import CalendarAdminMixin

from .models import Appointment, Booking, Holiday, Professional, Room


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
    # Dragging saves (asking first).
    calendar_editable = True


@admin.register(Holiday)
class HolidayAdmin(CalendarAdminMixin, admin.ModelAdmin):
    list_display = ("name", "first_day", "last_day")
    # Whole days (DateField): all-day events.
    calendar_start_field = "first_day"
    calendar_end_field = "last_day"
    calendar_views = ("dayGridMonth", "listYear")


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    list_display = ("name", "active")


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
    calendar_editable = True
    calendar_options = {"slotMinTime": "08:00", "slotMaxTime": "20:00"}

    def get_calendar_queryset(self, request):
        # The calendar only: not the cancelled ones.
        return super().get_calendar_queryset(request).exclude(status="cancelled")
