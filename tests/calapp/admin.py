"""The tests' admin site: calendars by each kind of resource."""

from django.contrib import admin

from django_ec_calendar import CalendarAdminMixin

from .models import Meeting

site = admin.AdminSite(name="calendars")


class ByAttendees(CalendarAdminMixin, admin.ModelAdmin):
    calendar_start_field = "start"
    calendar_duration_field = "length"
    calendar_resource_field = "attendees"
    calendar_detail_fields = ("host", "online", "day", "kind", "where")
    calendar_editable = True

    @admin.display(description="Place")
    def where(self, obj):
        return "Online" if obj.online else "Office"


site.register(Meeting, ByAttendees)
