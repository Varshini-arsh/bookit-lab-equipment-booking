import csv
from collections import Counter
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.db import connection, transaction
from django.db.models import Count, DurationField, ExpressionWrapper, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import AuditLog, Booking, Category, Certification, Equipment, audit
from .serializers import (
    AuditLogSerializer,
    BookingSerializer,
    CategorySerializer,
    CertificationSerializer,
    EquipmentSerializer,
    UserSerializer,
)
from .services import booking_problems, find_conflicts, is_manager

USED = (Booking.Status.APPROVED, Booking.Status.CHECKED_OUT, Booking.Status.RETURNED)
DURATION = ExpressionWrapper(F("end") - F("start"), output_field=DurationField())


class IsManagerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS or is_manager(request.user)


def require_manager(user):
    if not is_manager(user):
        raise PermissionDenied("Only lab managers can do this.")


def parse_when(value, name):
    dt = parse_datetime(value or "")
    if dt is None:
        raise ValidationError({name: "Use an ISO date-time, e.g. 2026-10-22T10:00:00+05:30."})
    return dt if timezone.is_aware(dt) else timezone.make_aware(dt)


@api_view(["GET"])
def me(request):
    user = request.user
    data = UserSerializer(user).data
    mine = Booking.objects.filter(user=user)
    data["is_manager"] = is_manager(user)
    data["certified_category_ids"] = [
        c.category_id for c in Certification.objects.filter(user=user) if c.is_valid
    ]
    data["counts"] = {
        "upcoming": mine.filter(status__in=Booking.ACTIVE, end__gte=timezone.now()).count(),
        "pending_approvals": Booking.objects.filter(status=Booking.Status.PENDING).count() if data["is_manager"] else 0,
        "overdue": Booking.objects.filter(status=Booking.Status.CHECKED_OUT, end__lt=timezone.now()).count()
        if data["is_manager"] else mine.filter(status=Booking.Status.CHECKED_OUT, end__lt=timezone.now()).count(),
    }
    return Response(data)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer

    def get_queryset(self):
        qs = User.objects.filter(is_active=True).select_related("profile").order_by("first_name")
        return qs if is_manager(self.request.user) else qs.filter(pk=self.request.user.pk)


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated, IsManagerOrReadOnly]

    def get_queryset(self):
        return Category.objects.annotate(equipment_count=Count("equipment")).order_by("name")


class EquipmentViewSet(viewsets.ModelViewSet):
    serializer_class = EquipmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsManagerOrReadOnly]

    def get_queryset(self):
        qs = Equipment.objects.select_related("category")
        params = self.request.query_params
        if params.get("category"):
            qs = qs.filter(category_id=params["category"])
        if params.get("search"):
            term = params["search"]
            qs = qs.filter(Q(name__icontains=term) | Q(asset_tag__icontains=term) | Q(location__icontains=term)
                           | Q(category__name__icontains=term))
        return qs

    def attach_live_status(self, items):
        """Mark each item with the booking in use right now and the next one today+ (2 queries total)."""
        now = timezone.now()
        ids = [e.id for e in items]
        current = {
            b.equipment_id: b for b in Booking.objects.filter(
                equipment_id__in=ids, status__in=(Booking.Status.APPROVED, Booking.Status.CHECKED_OUT),
                start__lte=now, end__gt=now).select_related("user")
        }
        upcoming = {}
        for b in Booking.objects.filter(equipment_id__in=ids, status__in=Booking.ACTIVE, start__gt=now).order_by("start"):
            upcoming.setdefault(b.equipment_id, b)
        for e in items:
            e._current = current.get(e.id)
            e._next = upcoming.get(e.id)
        return items

    def list(self, request, *args, **kwargs):
        items = self.attach_live_status(list(self.get_queryset()))
        if request.query_params.get("available") == "1":
            items = [e for e in items if e.bookable and e._current is None]
        return Response(self.get_serializer(items, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        item = self.attach_live_status([self.get_object()])[0]
        return Response(self.get_serializer(item).data)

    def perform_create(self, serializer):
        e = serializer.save()
        audit(self.request.user, "equipment added", equipment=e, detail=e.name)

    def perform_update(self, serializer):
        e = serializer.save()
        audit(self.request.user, "equipment updated", equipment=e, detail=f"condition: {e.get_condition_display()}")

    @action(detail=True)
    def schedule(self, request, pk=None):
        """Bookings for a week: ?start=YYYY-MM-DD (defaults to this Monday)&days=7."""
        equipment = self.get_object()
        today = timezone.localdate()
        first = parse_date(request.query_params.get("start", "")) or (today - timedelta(days=today.weekday()))
        days = min(int(request.query_params.get("days", 7)), 31)
        tz = timezone.get_current_timezone()
        window_start = timezone.make_aware(datetime.combine(first, time.min), tz)
        window_end = window_start + timedelta(days=days)
        bookings = (
            Booking.objects.filter(equipment=equipment, start__lt=window_end, end__gt=window_start)
            .exclude(status__in=(Booking.Status.REJECTED, Booking.Status.CANCELLED))
            .select_related("user__profile")
        )
        return Response({
            "start": first.isoformat(),
            "days": days,
            "bookings": [
                {
                    "id": b.id, "start": b.start, "end": b.end, "status": b.status, "status_label": b.get_status_display(),
                    "mine": b.user_id == request.user.id, "user": b.user.get_full_name() or b.user.username,
                    "color": b.user.profile.color, "purpose": b.purpose if (b.user_id == request.user.id or is_manager(request.user)) else "",
                }
                for b in bookings
            ],
        })


class BookingViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BookingSerializer

    def get_queryset(self):
        user = self.request.user
        params = self.request.query_params
        qs = Booking.objects.select_related("equipment__category", "user__profile", "decided_by")
        if not (is_manager(user) and params.get("scope") == "all"):
            qs = qs.filter(user=user)
        if params.get("status"):
            qs = qs.filter(status__in=params["status"].split(","))
        now = timezone.now()
        if params.get("when") == "upcoming":
            qs = qs.filter(end__gte=now).order_by("start")
        elif params.get("when") == "past":
            qs = qs.filter(end__lt=now).order_by("-start")
        elif params.get("when") == "today":
            # A datetime range rather than __date: MySQL's __date needs time-zone tables loaded.
            midnight = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
            qs = qs.filter(start__lt=midnight + timedelta(days=1), end__gt=midnight).order_by("start")
        else:
            qs = qs.order_by("-start")  # full history: newest first
        if params.get("equipment"):
            qs = qs.filter(equipment_id=params["equipment"])
        return qs

    def get_object(self):
        # Managers can act on anyone's booking; members only on their own.
        qs = Booking.objects.select_related("equipment__category", "user__profile")
        if not is_manager(self.request.user):
            qs = qs.filter(user=self.request.user)
        return get_object_or_404(qs, pk=self.kwargs["pk"])

    def perform_create(self, serializer):
        equipment = serializer.validated_data["equipment_id"]
        if equipment.requires_approval:
            booking = serializer.save(user=self.request.user, status=Booking.Status.PENDING)
            audit(self.request.user, "requested", booking=booking, detail=booking.purpose)
        else:
            booking = serializer.save(user=self.request.user, status=Booking.Status.APPROVED, decided_at=timezone.now())
            audit(self.request.user, "booked", booking=booking, detail="auto-approved")

    @action(detail=False)
    def check(self, request):
        """Live validation for the booking form: returns every problem, not just the first."""
        equipment = get_object_or_404(Equipment.objects.select_related("category"), pk=request.query_params.get("equipment"))
        start = parse_when(request.query_params.get("start"), "start")
        end = parse_when(request.query_params.get("end"), "end")
        problems = booking_problems(request.user, equipment, start, end)
        return Response({
            "ok": not problems,
            "problems": problems,
            "hours": round(max((end - start).total_seconds(), 0) / 3600, 2),
            "requires_approval": equipment.requires_approval,
        })

    def transition(self, request, allowed_from, new_status, *, manager_only=True, note_required=False, stamp=None, extra=None):
        booking = self.get_object()
        if manager_only:
            require_manager(request.user)
        if booking.status not in allowed_from:
            raise ValidationError({"status": f"Can't do that while the booking is '{booking.get_status_display()}'."})
        note = (request.data.get("note") or "").strip()
        if note_required and not note:
            raise ValidationError({"note": "Please give the member a reason."})
        with transaction.atomic():
            booking.status = new_status
            if note:
                booking.manager_note = note[:200]
            if stamp:
                setattr(booking, stamp, timezone.now())
            for attr, value in (extra or {}).items():
                setattr(booking, attr, value)
            booking.save()
            audit(request.user, new_status.replace("_", " "), booking=booking, detail=note)
        return Response(BookingSerializer(booking, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        booking = self.get_object()
        require_manager(request.user)
        clashes = find_conflicts(booking.equipment, booking.start, booking.end, exclude_id=booking.id).filter(
            status__in=(Booking.Status.APPROVED, Booking.Status.CHECKED_OUT))
        if clashes.exists():
            raise ValidationError({"status": "Another approved booking already holds this slot."})
        return self.transition(request, [Booking.Status.PENDING], Booking.Status.APPROVED,
                               stamp="decided_at", extra={"decided_by": request.user})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self.transition(request, [Booking.Status.PENDING], Booking.Status.REJECTED, note_required=True,
                               stamp="decided_at", extra={"decided_by": request.user})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        if not is_manager(request.user) and booking.start <= timezone.now():
            raise ValidationError({"status": "This booking has already started; ask a lab manager."})
        return self.transition(request, [Booking.Status.PENDING, Booking.Status.APPROVED], Booking.Status.CANCELLED, manager_only=False)

    @action(detail=True, methods=["post"])
    def checkout(self, request, pk=None):
        booking = self.get_object()
        if booking.start - timezone.now() > timedelta(minutes=30):
            raise ValidationError({"status": "Check-out opens 30 minutes before the booking starts."})
        return self.transition(request, [Booking.Status.APPROVED], Booking.Status.CHECKED_OUT, stamp="checked_out_at")

    @action(detail=True, methods=["post"], url_path="return")
    def mark_returned(self, request, pk=None):
        return self.transition(request, [Booking.Status.CHECKED_OUT], Booking.Status.RETURNED, stamp="returned_at")


class CertificationViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = CertificationSerializer

    def get_queryset(self):
        qs = Certification.objects.select_related("user__profile", "category")
        return qs if is_manager(self.request.user) else qs.filter(user=self.request.user)

    def perform_create(self, serializer):
        require_manager(self.request.user)
        cert = serializer.save(granted_by=self.request.user)
        audit(self.request.user, "certified", detail=f"{cert.user.get_full_name()} for {cert.category.name}")

    def perform_destroy(self, instance):
        require_manager(self.request.user)
        audit(self.request.user, "revoked certification", detail=f"{instance.user.get_full_name()} for {instance.category.name}")
        instance.delete()


class AuditViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        require_manager(self.request.user)
        return AuditLog.objects.select_related("actor__profile", "equipment")[:100]


DEPARTMENT_SQL = """
    SELECT p.department,
           COUNT(b.id)               AS bookings,
           COUNT(DISTINCT b.user_id) AS people
    FROM core_booking b
    JOIN auth_user u    ON u.id = b.user_id
    JOIN core_profile p ON p.user_id = u.id
    WHERE b.start >= %s AND b.start < %s AND b.status IN (%s, %s, %s)
    GROUP BY p.department
    ORDER BY bookings DESC
"""


def report_window(request):
    try:
        days = max(1, min(int(request.query_params.get("days", 30)), 180))
    except ValueError:
        days = 30
    now = timezone.now()
    return days, now - timedelta(days=days), now


@api_view(["GET"])
def report_summary(request):
    require_manager(request.user)
    days, since, now = report_window(request)
    in_window = Booking.objects.filter(start__gte=since, start__lt=now)
    used = in_window.filter(status__in=USED)

    total = used.aggregate(h=Sum(DURATION))["h"] or timedelta()
    active_equipment = Equipment.objects.filter(is_active=True).exclude(condition=Equipment.Condition.NEEDS_REPAIR).count()
    capacity_hours = active_equipment * 12 * days
    decided = in_window.filter(status__in=USED + (Booking.Status.REJECTED,)).filter(decided_by__isnull=False)

    top = (
        used.values("equipment_id", "equipment__name", "equipment__asset_tag", "equipment__category__name")
        .annotate(n=Count("id"), dur=Sum(DURATION))
        .order_by("-dur")[:8]
    )
    with connection.cursor() as cursor:
        cursor.execute(DEPARTMENT_SQL, [since, now, *USED])
        departments = [{"department": r[0], "bookings": r[1], "people": r[2]} for r in cursor.fetchall()]

    # Daily trend + weekday x hour heatmap, bucketed in local time (DB-agnostic).
    per_day = Counter()
    heat = Counter()
    for start, end in used.values_list("start", "end"):
        s, e = timezone.localtime(start), timezone.localtime(end)
        per_day[s.date()] += 1
        hour = s.replace(minute=0, second=0, microsecond=0)
        while hour < e:
            heat[(hour.weekday(), hour.hour)] += 1
            hour += timedelta(hours=1)
    first_day = timezone.localdate() - timedelta(days=days - 1)

    return Response({
        "days": days,
        "stats": {
            "bookings": in_window.count(),
            "hours": round(total.total_seconds() / 3600, 1),
            "utilization": round(100 * total.total_seconds() / 3600 / capacity_hours, 1) if capacity_hours else 0,
            "people": used.values("user").distinct().count(),
            "pending": Booking.objects.filter(status=Booking.Status.PENDING).count(),
            "overdue": Booking.objects.filter(status=Booking.Status.CHECKED_OUT, end__lt=now).count(),
            "rejection_rate": round(100 * decided.filter(status=Booking.Status.REJECTED).count() / decided.count(), 1) if decided.count() else 0,
        },
        "top_equipment": [
            {"id": t["equipment_id"], "name": t["equipment__name"], "asset_tag": t["equipment__asset_tag"],
             "category": t["equipment__category__name"], "bookings": t["n"],
             "hours": round((t["dur"] or timedelta()).total_seconds() / 3600, 1)}
            for t in top
        ],
        "departments": departments,
        "status_breakdown": [
            {"status": s, "label": label, "count": in_window.filter(status=s).count()} for s, label in Booking.Status.choices
        ],
        "daily": [
            {"date": (first_day + timedelta(days=i)).isoformat(), "count": per_day[first_day + timedelta(days=i)]}
            for i in range(days)
        ],
        "heatmap": [[heat[(wd, h)] for h in range(8, 20)] for wd in range(7)],
    })


@api_view(["GET"])
def report_export(request):
    require_manager(request.user)
    days, since, now = report_window(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="bookit-bookings-last-{days}-days.csv"'
    writer = csv.writer(response)
    writer.writerow(["Booking ID", "Asset tag", "Equipment", "Category", "Member", "Department",
                     "Start", "End", "Hours", "Status", "Purpose", "Manager note"])
    rows = (Booking.objects.filter(start__gte=since, start__lt=now)
            .select_related("equipment__category", "user__profile").order_by("start"))
    for b in rows:
        writer.writerow([
            b.id, b.equipment.asset_tag, b.equipment.name, b.equipment.category.name,
            b.user.get_full_name() or b.user.username, b.user.profile.department,
            timezone.localtime(b.start).strftime("%Y-%m-%d %H:%M"), timezone.localtime(b.end).strftime("%Y-%m-%d %H:%M"),
            b.hours, b.get_status_display(), b.purpose, b.manager_note,
        ])
    return response
