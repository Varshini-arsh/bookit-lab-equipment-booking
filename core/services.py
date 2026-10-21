"""Booking rules live here so the API, the live "check" endpoint and the tests share one implementation."""
from datetime import timedelta

from django.utils import timezone

from .models import CLOSE_HOUR, OPEN_HOUR, Booking, Certification, Profile


def is_manager(user):
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == Profile.Role.MANAGER)


def has_certification(user, category):
    if not category.requires_certification:
        return True
    cert = Certification.objects.filter(user=user, category=category).first()
    return bool(cert and cert.is_valid)


def find_conflicts(equipment, start, end, exclude_id=None):
    """Two intervals overlap when each starts before the other ends.

    SQL: ... WHERE equipment_id = %s AND status IN ('pending','approved','checked_out')
                 AND start < %(end)s AND "end" > %(start)s
    Back-to-back bookings (one ends 14:00, next starts 14:00) do not conflict.
    """
    qs = Booking.objects.filter(equipment=equipment, status__in=Booking.ACTIVE, start__lt=end, end__gt=start)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.select_related("user")


def booking_problems(user, equipment, start, end, exclude_id=None):
    """Return a list of human-readable reasons this booking can't be made (empty = OK)."""
    problems = []
    if end <= start:
        return ["End time must be after the start time."]

    now = timezone.now()
    if start < now - timedelta(minutes=5):
        problems.append("You can't book a slot that has already started.")
    if start > now + timedelta(days=60):
        problems.append("Bookings open at most 60 days ahead.")

    local_start, local_end = timezone.localtime(start), timezone.localtime(end)
    if local_start.date() != local_end.date():
        problems.append("A booking must start and end on the same day.")
    elif local_start.hour < OPEN_HOUR or (local_end.hour, local_end.minute) > (CLOSE_HOUR, 0):
        problems.append(f"The lab is open {OPEN_HOUR:02d}:00-{CLOSE_HOUR:02d}:00.")

    hours = (end - start).total_seconds() / 3600
    if hours > equipment.max_hours:
        problems.append(f"{equipment.name} can be booked for at most {equipment.max_hours} hours at a time.")

    if not equipment.bookable:
        problems.append(f"{equipment.name} is out of service ({equipment.get_condition_display().lower()}).")

    if not has_certification(user, equipment.category):
        problems.append(
            f"{equipment.category.name} require a safety certification. Ask a lab manager to certify you first."
        )

    for c in find_conflicts(equipment, start, end, exclude_id):
        who = "you" if c.user_id == user.id else (c.user.get_full_name() or c.user.username)
        problems.append(
            f"Overlaps with a booking by {who}, "
            f"{timezone.localtime(c.start):%a %d %b %H:%M}-{timezone.localtime(c.end):%H:%M}."
        )
    return problems
