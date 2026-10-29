"""The demo's admin on an Unfold site (see ``example.settings_unfold``)."""

from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.sites import UnfoldAdminSite

from django_ec_calendar import CalendarAdminMixin

from .models import Appointment, Booking, Holiday, Professional, Room

site = UnfoldAdminSite(name="admin")


@admin.register(Room, site=site)
class RoomAdmin(ModelAdmin):
    list_display = ("name", "color")


@admin.register(Booking, site=site)
class BookingAdmin(CalendarAdminMixin, ModelAdmin):
    list_display = ("title", "room", "start", "end")
    list_filter = ("room",)
    list_select_related = ("room",)
    search_fields = ("title",)
    calendar_start_field = "start"
    calendar_end_field = "end"
    calendar_color_field = "color"
    calendar_view = "timeGridWeek"
    calendar_options = {"slotMinTime": "07:00", "slotMaxTime": "21:00"}
    calendar_editable = True


@admin.register(Holiday, site=site)
class HolidayAdmin(CalendarAdminMixin, ModelAdmin):
    list_display = ("name", "first_day", "last_day")
    calendar_start_field = "first_day"
    calendar_end_field = "last_day"
    calendar_views = ("dayGridMonth", "listYear")


@admin.register(Professional, site=site)
class ProfessionalAdmin(ModelAdmin):
    list_display = ("name", "active")


@admin.register(Appointment, site=site)
class AppointmentAdmin(CalendarAdminMixin, ModelAdmin):
    list_display = ("client", "professional", "start", "minutes", "status")
    list_filter = ("professional", "status")
    list_select_related = ("professional",)
    search_fields = ("client",)
    calendar_start_field = "start"
    calendar_duration_field = "minutes"
    calendar_resource_field = "professional"
    calendar_detail_fields = ("get_status_display",)
    calendar_view = "resourceTimeGridDay"
    calendar_views = ("resourceTimeGridDay", "resourceTimeGridWeek", "listWeek")
    calendar_editable = True
    calendar_options = {"slotMinTime": "08:00", "slotMaxTime": "20:00"}

    def get_calendar_queryset(self, request):
        return super().get_calendar_queryset(request).exclude(status="cancelled")
