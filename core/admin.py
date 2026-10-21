from django.contrib import admin

from .models import AuditLog, Booking, Category, Certification, Equipment, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "department", "title"]
    list_filter = ["role", "department"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "requires_certification"]


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ["asset_tag", "name", "category", "location", "condition", "requires_approval", "is_active"]
    list_filter = ["category", "condition", "requires_approval", "is_active"]
    search_fields = ["name", "asset_tag"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["equipment", "user", "start", "end", "status"]
    list_filter = ["status", "equipment__category"]
    date_hierarchy = "start"


admin.site.register(Certification)
admin.site.register(AuditLog)
