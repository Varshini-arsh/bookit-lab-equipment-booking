from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import AuditLog, Booking, Category, Certification, Equipment, Profile


def make_user(username, role=Profile.Role.MEMBER):
    user = User.objects.create_user(username=username, password="pass12345", first_name=username.title())
    Profile.objects.filter(user=user).update(role=role)
    user.refresh_from_db()
    return user


def tomorrow_at(hour, minute=0):
    day = timezone.localdate() + timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)), timezone.get_current_timezone())


class BookingRulesTests(APITestCase):
    def setUp(self):
        self.manager = make_user("manager", Profile.Role.MANAGER)
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.open_cat = Category.objects.create(name="Oscilloscopes")
        self.safe_cat = Category.objects.create(name="3D Printers", requires_certification=True)
        self.scope = Equipment.objects.create(name="Scope", asset_tag="OSC-1", category=self.open_cat, location="A1", max_hours=4)
        self.printer = Equipment.objects.create(name="Printer", asset_tag="3DP-1", category=self.safe_cat, location="M",
                                                requires_approval=True, max_hours=8)

    def book(self, user, equipment, start, end, purpose="Lab work"):
        self.client.force_authenticate(user)
        return self.client.post("/api/bookings/", {
            "equipment_id": equipment.id, "start": start.isoformat(), "end": end.isoformat(), "purpose": purpose,
        }, format="json")

    # --- validation ---
    def test_open_equipment_is_auto_approved(self):
        res = self.book(self.alice, self.scope, tomorrow_at(10), tomorrow_at(12))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["status"], "approved")
        self.assertTrue(AuditLog.objects.filter(action="booked").exists())

    def test_overlap_is_rejected_but_back_to_back_is_fine(self):
        self.assertEqual(self.book(self.alice, self.scope, tomorrow_at(10), tomorrow_at(12)).status_code, 201)
        clash = self.book(self.bob, self.scope, tomorrow_at(11), tomorrow_at(13))
        self.assertEqual(clash.status_code, 400)
        self.assertIn("Overlaps with a booking by Alice", " ".join(clash.json()["non_field_errors"]))
        self.assertEqual(self.book(self.bob, self.scope, tomorrow_at(12), tomorrow_at(14)).status_code, 201)

    def test_cancelled_booking_frees_the_slot(self):
        first = self.book(self.alice, self.scope, tomorrow_at(10), tomorrow_at(12)).json()
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.post(f"/api/bookings/{first['id']}/cancel/").status_code, 200)
        self.assertEqual(self.book(self.bob, self.scope, tomorrow_at(10), tomorrow_at(12)).status_code, 201)

    def test_opening_hours_and_max_duration(self):
        early = self.book(self.alice, self.scope, tomorrow_at(6), tomorrow_at(9))
        self.assertIn("The lab is open 08:00-20:00.", early.json()["non_field_errors"])
        long = self.book(self.alice, self.scope, tomorrow_at(9), tomorrow_at(15))
        self.assertIn("at most 4 hours", " ".join(long.json()["non_field_errors"]))

    def test_end_before_start_and_past_slots(self):
        backwards = self.book(self.alice, self.scope, tomorrow_at(12), tomorrow_at(10))
        self.assertEqual(backwards.json()["non_field_errors"], ["End time must be after the start time."])
        past = self.book(self.alice, self.scope, tomorrow_at(10) - timedelta(days=3), tomorrow_at(11) - timedelta(days=3))
        self.assertIn("already started", " ".join(past.json()["non_field_errors"]))

    def test_out_of_service_equipment_cannot_be_booked(self):
        self.scope.condition = Equipment.Condition.NEEDS_REPAIR
        self.scope.save()
        res = self.book(self.alice, self.scope, tomorrow_at(10), tomorrow_at(11))
        self.assertIn("out of service", " ".join(res.json()["non_field_errors"]))

    # --- certification gate ---
    def test_certification_required_for_restricted_category(self):
        res = self.book(self.alice, self.printer, tomorrow_at(10), tomorrow_at(12))
        self.assertEqual(res.status_code, 400)
        self.assertIn("require a safety certification", " ".join(res.json()["non_field_errors"]))
        Certification.objects.create(user=self.alice, category=self.safe_cat, granted_by=self.manager)
        res = self.book(self.alice, self.printer, tomorrow_at(10), tomorrow_at(12))
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["status"], "pending")

    def test_expired_certification_does_not_count(self):
        Certification.objects.create(user=self.alice, category=self.safe_cat,
                                     expires_on=timezone.localdate() - timedelta(days=1))
        self.assertEqual(self.book(self.alice, self.printer, tomorrow_at(10), tomorrow_at(12)).status_code, 400)

    def test_only_managers_grant_certifications(self):
        self.client.force_authenticate(self.alice)
        payload = {"user_id": self.alice.id, "category_id": self.safe_cat.id}
        self.assertEqual(self.client.post("/api/certifications/", payload, format="json").status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post("/api/certifications/", payload, format="json").status_code, 201)

    # --- approval workflow ---
    def pending_print(self):
        Certification.objects.create(user=self.alice, category=self.safe_cat)
        return self.book(self.alice, self.printer, tomorrow_at(10), tomorrow_at(12)).json()

    def test_member_cannot_approve(self):
        b = self.pending_print()
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.post(f"/api/bookings/{b['id']}/approve/").status_code, 403)

    def test_manager_approve_then_checkout_and_return(self):
        b = self.pending_print()
        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/bookings/{b['id']}/approve/")
        self.assertEqual(res.json()["status"], "approved")
        self.assertEqual(res.json()["decided_by"], "Manager")
        # Too early to check out (starts tomorrow).
        self.assertEqual(self.client.post(f"/api/bookings/{b['id']}/checkout/").status_code, 400)
        Booking.objects.filter(pk=b["id"]).update(start=timezone.now() + timedelta(minutes=10))
        self.assertEqual(self.client.post(f"/api/bookings/{b['id']}/checkout/").json()["status"], "checked_out")
        self.assertEqual(self.client.post(f"/api/bookings/{b['id']}/return/").json()["status"], "returned")

    def test_reject_requires_a_note(self):
        b = self.pending_print()
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(f"/api/bookings/{b['id']}/reject/", {}, format="json").status_code, 400)
        self.assertEqual(Booking.objects.get(pk=b["id"]).status, "pending")
        res = self.client.post(f"/api/bookings/{b['id']}/reject/", {"note": "Printer maintenance"}, format="json")
        self.assertEqual(res.json()["status"], "rejected")
        self.assertEqual(res.json()["manager_note"], "Printer maintenance")

    def test_members_only_see_and_touch_their_own_bookings(self):
        b = self.book(self.alice, self.scope, tomorrow_at(10), tomorrow_at(12)).json()
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.post(f"/api/bookings/{b['id']}/cancel/").status_code, 404)
        self.assertEqual(self.client.get("/api/bookings/?scope=all").json(), [])

    # --- live check + reports ---
    def test_check_endpoint_lists_every_problem(self):
        self.client.force_authenticate(self.alice)
        res = self.client.get("/api/bookings/check/", {
            "equipment": self.printer.id, "start": tomorrow_at(7).isoformat(), "end": tomorrow_at(17).isoformat(),
        })
        data = res.json()
        self.assertFalse(data["ok"])
        self.assertEqual(len(data["problems"]), 3)  # hours, duration, certification
        self.assertTrue(data["requires_approval"])

    def test_reports_are_manager_only_and_count_hours(self):
        self.book(self.alice, self.scope, tomorrow_at(10), tomorrow_at(12))
        Booking.objects.update(start=timezone.now() - timedelta(days=2), end=timezone.now() - timedelta(days=2) + timedelta(hours=2),
                               status=Booking.Status.RETURNED)
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.get("/api/reports/summary/").status_code, 403)
        self.client.force_authenticate(self.manager)
        data = self.client.get("/api/reports/summary/?days=7").json()
        self.assertEqual(data["stats"]["hours"], 2.0)
        self.assertEqual(data["top_equipment"][0]["asset_tag"], "OSC-1")
        self.assertEqual(data["departments"][0]["bookings"], 1)
        csv_body = self.client.get("/api/reports/export.csv?days=7").content.decode()
        self.assertIn("OSC-1", csv_body)
