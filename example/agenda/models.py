from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse


class Room(models.Model):
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, blank=True, help_text="A CSS color.")

    def __str__(self) -> str:
        return self.name


class Booking(models.Model):
    """At a time: from its start to its end."""

    title = models.CharField(max_length=100)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bookings")
    start = models.DateTimeField()
    end = models.DateTimeField()

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("booking", args=[self.pk])

    def clean(self) -> None:
        if self.start and self.end and self.end < self.start:
            raise ValidationError("It can't end before it starts.")

    @property
    def color(self) -> str:
        return self.room.color


class Holiday(models.Model):
    """Whole days: from its first to its last."""

    name = models.CharField(max_length=100)
    first_day = models.DateField()
    last_day = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class Professional(models.Model):
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class Appointment(models.Model):
    """A professional's (or nobody's yet), for some minutes."""

    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    client = models.CharField(max_length=100)
    professional = models.ForeignKey(
        Professional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"active": True},
        related_name="appointments",
    )
    start = models.DateTimeField()
    minutes = models.PositiveIntegerField(default=30)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.BOOKED
    )

    def __str__(self) -> str:
        return self.client
