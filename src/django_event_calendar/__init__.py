"""A calendar for the Django admin and your pages, with EventCalendar."""

from .admin import CalendarAdminMixin
from .source import CalendarSource
from .views import EventFeedView

__all__ = ["CalendarAdminMixin", "CalendarSource", "EventFeedView"]

__version__ = "0.1.0"
