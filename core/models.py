from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

# The lab is staffed 08:00-20:00 (settings.TIME_ZONE); bookings must fit inside that window.
OPEN_HOUR = 8
CLOSE_HOUR = 20


class Profile(models.Model):
    class Role(models.TextChoices):
        MEMBER = "member", "Lab member"
        MANAGER = "manager", "Lab manager"

    class Department(models.TextChoices):
        ECE = "ECE", "Electronics & Communication"
        CSE = "CSE", "Computer Science"
        MECH = "MECH", "Mechanical"
        PHY = "PHY", "Physics"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    department = models.CharField(max_length=10, choices=Department.choices, default=Department.ECE)
    title = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=7, default="#6250d6")

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    icon = models.CharField(max_length=20, default="box", help_text="Icon key used by the frontend")
    description = models.CharField(max_length=200, blank=True)
    requires_certification = models.BooleanField(
        default=False, help_text="Members need a safety/training certification for this category before booking."
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Equipment(models.Model):
    class Condition(models.TextChoices):
        EXCELLENT = "excellent", "Excellent"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"
        NEEDS_REPAIR = "needs_repair", "Needs repair"

    name = models.CharField(max_length=120)
    asset_tag = models.CharField(max_length=20, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="equipment")
    location = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.GOOD)
    requires_approval = models.BooleanField(default=False, help_text="Bookings stay pending until a lab manager approves.")
    max_hours = models.PositiveSmallIntegerField(default=4)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category__name", "name"]

    @property
    def bookable(self):
        return self.is_active and self.condition != self.Condition.NEEDS_REPAIR

    def __str__(self):
        return f"{self.asset_tag} · {self.name}"


class Certification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="certifications")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="certifications")
    granted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_on = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "category"], name="unique_user_category_cert")]

    @property
    def is_valid(self):
        return self.expires_on is None or self.expires_on >= timezone.localdate()


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        CHECKED_OUT = "checked_out", "Checked out"
        RETURNED = "returned", "Returned"

    # Statuses that hold the slot: anything overlapping one of these is a conflict.
    ACTIVE = (Status.PENDING, Status.APPROVED, Status.CHECKED_OUT)

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="bookings")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    start = models.DateTimeField()
    end = models.DateTimeField()
    purpose = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    manager_note = models.CharField(max_length=200, blank=True)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start"]
        indexes = [
            models.Index(fields=["equipment", "start", "end"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "start"]),
        ]

    @property
    def hours(self):
        return round((self.end - self.start).total_seconds() / 3600, 2)

    @property
    def is_overdue(self):
        return self.status == self.Status.CHECKED_OUT and self.end < timezone.now()

    def __str__(self):
        return f"{self.equipment.asset_tag} {self.start:%Y-%m-%d %H:%M} ({self.status})"


class AuditLog(models.Model):
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    booking = models.ForeignKey(Booking, null=True, blank=True, on_delete=models.SET_NULL)
    equipment = models.ForeignKey(Equipment, null=True, blank=True, on_delete=models.SET_NULL)
    detail = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


def audit(actor, action, *, booking=None, equipment=None, detail=""):
    AuditLog.objects.create(
        actor=actor, action=action, booking=booking, equipment=equipment or (booking.equipment if booking else None),
        detail=detail[:250],
    )
