"""The demo's admin on an Unfold site (see ``example.settings_unfold``)."""

from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.sites import UnfoldAdminSite

from django_event_calendar import CalendarAdminMixin

from .models import Booking, Holiday, Room

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


@admin.register(Holiday, site=site)
class HolidayAdmin(CalendarAdminMixin, ModelAdmin):
    list_display = ("name", "first_day", "last_day")
    calendar_start_field = "first_day"
    calendar_end_field = "last_day"
    calendar_views = ("dayGridMonth", "listYear")
