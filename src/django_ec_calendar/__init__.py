"""A calendar for the Django admin and your pages, with EventCalendar."""

from .admin import CalendarAdminMixin, CalendarInline
from .core import CalendarMixin, CalendarMove, CalendarMoveError
from .source import CalendarSource
from .views import CalendarView, EventFeedView
from .widget import Calendar

__all__ = [
    "Calendar",
    "CalendarAdminMixin",
    "CalendarInline",
    "CalendarMixin",
    "CalendarMove",
    "CalendarMoveError",
    "CalendarSource",
    "CalendarView",
    "EventFeedView",
]

__version__ = "0.1.2"
