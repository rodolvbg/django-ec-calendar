from agenda import views
from agenda.admin_unfold import site
from django.urls import include, path

urlpatterns = [
    path("admin/", site.urls),
    path("", views.calendar, name="calendar"),
    path("events/", views.BookingEvents.as_view(), name="booking-events"),
    path("bookings/<int:pk>/", views.booking, name="booking"),
    # A professional's agenda, out of the admin (CalendarView).
    path("agenda/<int:pk>/", include(views.ProfessionalAgenda.urls("agenda"))),
]
