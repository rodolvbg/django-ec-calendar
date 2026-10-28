from agenda import views
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.calendar, name="calendar"),
    path("events/", views.BookingEvents.as_view(), name="booking-events"),
    path("bookings/<int:pk>/", views.booking, name="booking"),
]
