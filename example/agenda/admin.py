from django.contrib import admin

from django_ec_calendar import CalendarAdminMixin

from .models import Booking, Holiday, Room


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


@admin.register(Holiday)
class HolidayAdmin(CalendarAdminMixin, admin.ModelAdmin):
    list_display = ("name", "first_day", "last_day")
    # Whole days (DateField): all-day events.
    calendar_start_field = "first_day"
    calendar_end_field = "last_day"
    calendar_views = ("dayGridMonth", "listYear")
