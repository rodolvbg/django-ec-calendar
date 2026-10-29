"""A calendar for the Django admin and your pages, with EventCalendar."""

from .admin import CalendarAdminMixin, CalendarMove, CalendarMoveError
from .source import CalendarSource
from .views import EventFeedView

__all__ = [
    "CalendarAdminMixin",
    "CalendarMove",
    "CalendarMoveError",
    "CalendarSource",
    "EventFeedView",
]

__version__ = "0.1.2"
