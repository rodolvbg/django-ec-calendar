"""Models only the tests use: resources of every kind, and durations."""

from django.db import models


class Person(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Meeting(models.Model):
    class Kind(models.TextChoices):
        CALL = "call", "Call"
        VISIT = "visit", "Visit"

    title = models.CharField(max_length=100)
    start = models.DateTimeField()
    length = models.DurationField(null=True, blank=True)
    attendees = models.ManyToManyField(Person, blank=True, related_name="meetings")
    kind = models.CharField(max_length=10, choices=Kind.choices, blank=True)
    host = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="hosted", null=True
    )
    online = models.BooleanField(default=False)
    day = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return f"/meetings/{self.pk}/"
