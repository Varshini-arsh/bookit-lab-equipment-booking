from django.contrib.auth.models import User
from rest_framework import serializers

from .models import AuditLog, Booking, Category, Certification, Equipment
from .services import booking_problems, has_certification


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    initials = serializers.SerializerMethodField()
    role = serializers.CharField(source="profile.role", read_only=True)
    role_label = serializers.CharField(source="profile.get_role_display", read_only=True)
    department = serializers.CharField(source="profile.department", read_only=True)
    title = serializers.CharField(source="profile.title", read_only=True)
    color = serializers.CharField(source="profile.color", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "name", "initials", "role", "role_label", "department", "title", "color"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_initials(self, obj):
        return "".join(p[0] for p in (obj.get_full_name() or obj.username).split()[:2]).upper()


class CategorySerializer(serializers.ModelSerializer):
    equipment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ["id", "name", "icon", "description", "requires_certification", "equipment_count"]


class EquipmentSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), source="category", write_only=True)
    condition_label = serializers.CharField(source="get_condition_display", read_only=True)
    bookable = serializers.BooleanField(read_only=True)
    certified = serializers.SerializerMethodField()
    current = serializers.SerializerMethodField()
    next_booking = serializers.SerializerMethodField()

    class Meta:
        model = Equipment
        fields = [
            "id", "name", "asset_tag", "category", "category_id", "location", "description", "condition",
            "condition_label", "requires_approval", "max_hours", "is_active", "bookable", "certified",
            "current", "next_booking",
        ]

    def get_certified(self, obj):
        request = self.context.get("request")
        return bool(request and has_certification(request.user, obj.category))

    # `current` / `next_booking` come from prefetch-free lookups stored on the instance by the view.
    def get_current(self, obj):
        b = getattr(obj, "_current", None)
        return {"end": b.end, "user": b.user.get_full_name() or b.user.username} if b else None

    def get_next_booking(self, obj):
        b = getattr(obj, "_next", None)
        return {"start": b.start, "end": b.end} if b else None


class BookingSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    equipment = serializers.SerializerMethodField()
    equipment_id = serializers.PrimaryKeyRelatedField(queryset=Equipment.objects.select_related("category"), write_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    hours = serializers.FloatField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    decided_by = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id", "equipment", "equipment_id", "user", "start", "end", "hours", "purpose", "status", "status_label",
            "manager_note", "decided_by", "decided_at", "checked_out_at", "returned_at", "is_overdue", "created_at",
        ]
        read_only_fields = ["status", "manager_note", "decided_at", "checked_out_at", "returned_at"]

    def get_equipment(self, obj):
        e = obj.equipment
        return {"id": e.id, "name": e.name, "asset_tag": e.asset_tag, "location": e.location,
                "category": e.category.name, "icon": e.category.icon}

    def get_decided_by(self, obj):
        return (obj.decided_by.get_full_name() or obj.decided_by.username) if obj.decided_by else None

    def validate_purpose(self, value):
        if len(value.strip()) < 4:
            raise serializers.ValidationError("Tell the lab manager briefly what it's for.")
        return value.strip()

    def validate(self, attrs):
        user = self.context["request"].user
        problems = booking_problems(user, attrs["equipment_id"], attrs["start"], attrs["end"])
        if problems:
            raise serializers.ValidationError({"non_field_errors": problems})
        return attrs

    def create(self, validated_data):
        validated_data["equipment"] = validated_data.pop("equipment_id")
        return super().create(validated_data)


class CertificationSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), source="user", write_only=True)
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.filter(requires_certification=True), source="category", write_only=True
    )
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Certification
        fields = ["id", "user", "user_id", "category", "category_id", "granted_at", "expires_on", "is_valid"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor = UserSerializer(read_only=True)
    equipment = serializers.CharField(source="equipment.name", default=None, read_only=True)

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "action", "equipment", "booking_id", "detail", "created_at"]
