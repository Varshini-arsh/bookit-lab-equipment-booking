from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("users", views.UserViewSet, basename="user")
router.register("categories", views.CategoryViewSet, basename="category")
router.register("equipment", views.EquipmentViewSet, basename="equipment")
router.register("bookings", views.BookingViewSet, basename="booking")
router.register("certifications", views.CertificationViewSet, basename="certification")
router.register("audit", views.AuditViewSet, basename="audit")

urlpatterns = [
    path("me/", views.me, name="me"),
    path("reports/summary/", views.report_summary, name="report-summary"),
    path("reports/export.csv", views.report_export, name="report-export"),
] + router.urls
