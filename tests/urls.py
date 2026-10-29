from django.urls import include, path

from tests.calapp.admin import site

urlpatterns = [
    path("calendars/", site.urls),
    path("", include("example.urls")),
]
