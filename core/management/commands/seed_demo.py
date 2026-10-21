"""Load the case-study dataset: a shared electronics & computing lab with 13 items and ~6 weeks of bookings.

    python manage.py seed_demo
"""
import random
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import AuditLog, Booking, Category, Certification, Equipment, Profile

DEMO_PASSWORD = "demo12345"

PEOPLE = [
    # username, first, last, role, dept, title, color, certified categories
    ("lakshmi", "Lakshmi", "Krishnan", Profile.Role.MANAGER, "ECE", "Lab Manager", "#6250d6", []),
    ("fatima", "Fatima", "Sheikh", Profile.Role.MEMBER, "CSE", "PhD Scholar · Machine Learning", "#2a78d6", ["GPU Workstations", "3D Printers"]),
    ("aditya", "Aditya", "Kulkarni", Profile.Role.MEMBER, "MECH", "M.Tech · Robotics", "#eb6834", ["3D Printers", "Soldering Stations"]),
    ("nikhil", "Nikhil", "Verma", Profile.Role.MEMBER, "ECE", "B.Tech · 3rd year", "#1baf7a", []),
    ("divya", "Divya", "Reddy", Profile.Role.MEMBER, "ECE", "M.Tech · VLSI Design", "#eda100", ["Soldering Stations"]),
    ("sameer", "Sameer", "Khan", Profile.Role.MEMBER, "PHY", "PhD Scholar · Optics", "#e87ba4", []),
    ("zoya", "Zoya", "Mathew", Profile.Role.MEMBER, "CSE", "B.Tech · Final year", "#008300", ["GPU Workstations"]),
]

CATEGORIES = [
    ("Oscilloscopes", "wave", "Digital storage oscilloscopes for signal debugging.", False),
    ("FPGA Boards", "chip", "Development boards for digital design and embedded labs.", False),
    ("3D Printers", "printer", "FDM and resin printers. Safety induction required.", True),
    ("GPU Workstations", "server", "Shared deep-learning machines. Usage policy sign-off required.", True),
    ("Soldering Stations", "flame", "Temperature-controlled irons. Safety induction required.", True),
]

EQUIPMENT = [
    # tag, name, category, location, condition, approval, max_hours, description
    ("OSC-01", "Keysight DSOX1204G", "Oscilloscopes", "Bench A1", "excellent", False, 4, "4-channel, 200 MHz, 2 GSa/s with built-in waveform generator."),
    ("OSC-02", "Keysight DSOX1204G", "Oscilloscopes", "Bench A2", "good", False, 4, "4-channel, 200 MHz. Probe set in the drawer below."),
    ("OSC-03", "Rigol DS1054Z", "Oscilloscopes", "Bench A3", "fair", False, 4, "4-channel, 50 MHz. Channel 3 is slightly noisy."),
    ("FPGA-01", "Digilent Basys 3 (Artix-7)", "FPGA Boards", "Cabinet C1", "good", False, 6, "Artix-7 35T, 16 switches, 4-digit 7-segment display."),
    ("FPGA-02", "Digilent Basys 3 (Artix-7)", "FPGA Boards", "Cabinet C1", "good", False, 6, "Artix-7 35T. Vivado 2025.2 licence on lab PCs."),
    ("FPGA-03", "PYNQ-Z2 (Zynq-7020)", "FPGA Boards", "Cabinet C2", "excellent", False, 6, "Zynq SoC with Python productivity layer."),
    ("FPGA-04", "Nexys A7-100T", "FPGA Boards", "Cabinet C2", "needs_repair", False, 6, "USB-JTAG port damaged; sent for repair."),
    ("3DP-01", "Prusa MK4", "3D Printers", "Maker Corner", "excellent", True, 8, "PLA/PETG, 250x210x220 mm build volume."),
    ("3DP-02", "Formlabs Form 3", "3D Printers", "Maker Corner", "good", True, 6, "Resin SLA printer. Gloves and IPA wash required."),
    ("GPU-01", "Workstation · RTX 4090 24 GB", "GPU Workstations", "Server Room", "excellent", True, 8, "Ryzen 9, 128 GB RAM, CUDA 12."),
    ("GPU-02", "Workstation · 2x RTX A6000", "GPU Workstations", "Server Room", "good", True, 12, "96 GB total VRAM for large models."),
    ("SOL-01", "Weller WE1010", "Soldering Stations", "Bench B1", "good", False, 3, "70 W digital station with fume extractor."),
    ("SOL-02", "Hakko FX-888D", "Soldering Stations", "Bench B2", "good", False, 3, "Includes brass tip cleaner and helping hands."),
]

PURPOSES = {
    "Oscilloscopes": ["Debug SPI timing on sensor board", "ADC noise measurement", "Lab 4: RC transient response", "PWM verification for motor driver"],
    "FPGA Boards": ["UART controller bring-up", "Digital design lab assignment", "Image filter on PL fabric", "Pipelined MIPS testing"],
    "3D Printers": ["Robot gripper prototype", "Enclosure for sensor node", "Drone frame parts v2", "Microfluidic mould"],
    "GPU Workstations": ["Fine-tune ViT on crop dataset", "Train LSTM battery SoH model", "Hyper-parameter sweep", "Inference benchmark"],
    "Soldering Stations": ["Assemble motor driver PCB", "Rework SMD resistors", "Sensor breakout soldering"],
}

# Weighted start hours: the lab is busiest late morning and mid-afternoon.
START_HOURS = [8, 9, 9, 10, 10, 10, 11, 11, 11, 12, 13, 14, 14, 14, 15, 15, 16, 16, 17, 18]


class Command(BaseCommand):
    help = "Reset BookIt data and load the shared-lab case study."

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(7)
        tz = timezone.get_current_timezone()
        now = timezone.now()
        today = timezone.localdate()

        AuditLog.objects.all().delete()
        Booking.objects.all().delete()
        Certification.objects.all().delete()
        Equipment.objects.all().delete()
        Category.objects.all().delete()
        User.objects.filter(username__in=[p[0] for p in PEOPLE]).delete()

        cats = {
            name: Category.objects.create(name=name, icon=icon, description=desc, requires_certification=cert)
            for name, icon, desc, cert in CATEGORIES
        }
        users, certified = {}, {}
        for username, first, last, role, dept, title, color, certs in PEOPLE:
            is_mgr = role == Profile.Role.MANAGER
            u = User.objects.create_user(username=username, password=DEMO_PASSWORD, first_name=first, last_name=last,
                                         email=f"{username}@lab.example", is_staff=is_mgr, is_superuser=is_mgr)
            Profile.objects.filter(user=u).update(role=role, department=dept, title=title, color=color)
            users[username] = u
            certified[username] = set(certs)
        manager = users["lakshmi"]
        for username, names in certified.items():
            for name in names:
                Certification.objects.create(user=users[username], category=cats[name], granted_by=manager,
                                             expires_on=today + timedelta(days=rng.randint(60, 300)))

        equipment = []
        for tag, name, cat, loc, cond, approval, max_h, desc in EQUIPMENT:
            equipment.append(Equipment.objects.create(
                asset_tag=tag, name=name, category=cats[cat], location=loc, condition=cond,
                requires_approval=approval, max_hours=max_h, description=desc,
            ))

        members = [u for u in users if u != "lakshmi"]

        def eligible(e):
            if not e.category.requires_certification:
                return members
            return [u for u in members if e.category.name in certified[u]]

        taken = {e.id: [] for e in equipment}
        busy = {u: [] for u in users}  # nobody uses two items at once

        def overlaps(intervals, s, en):
            return any(s < b_end and en > b_start for b_start, b_end in intervals)

        def free(e, s, en):
            return not overlaps(taken[e.id], s, en)

        def make(e, username, s, en, status, note=""):
            taken[e.id].append((s, en))
            busy[username].append((s, en))
            b = Booking.objects.create(equipment=e, user=users[username], start=s, end=en, status=status,
                                       purpose=rng.choice(PURPOSES[e.category.name]), manager_note=note)
            requested = s - timedelta(days=rng.randint(1, 6), hours=rng.randint(0, 8))
            stamps = {"created_at": min(requested, now - timedelta(minutes=rng.randint(20, 2 * 24 * 60)))}
            if status not in (Booking.Status.PENDING, Booking.Status.CANCELLED):
                stamps.update(decided_by=manager if e.requires_approval or status == Booking.Status.REJECTED else None,
                              decided_at=stamps["created_at"] + timedelta(hours=rng.randint(1, 20)))
            if status in (Booking.Status.CHECKED_OUT, Booking.Status.RETURNED):
                stamps["checked_out_at"] = s + timedelta(minutes=rng.randint(0, 10))
            if status == Booking.Status.RETURNED:
                stamps["returned_at"] = en - timedelta(minutes=rng.randint(0, 15))
            Booking.objects.filter(pk=b.pk).update(**stamps)
            return b

        # Hand-placed bookings that make the demo tell a story.
        def at(day_offset, hour, minute=0):
            return timezone.make_aware(datetime.combine(today + timedelta(days=day_offset), time(hour, minute)), tz)

        by_tag = {e.asset_tag: e for e in equipment}
        # "Live" bookings are relative to the current time but clamped to lab hours (08:00-20:00);
        # if the seed runs too early or late in the day, they are simply left out.
        opening, closing = at(0, 8), at(0, 20)

        def live(start, end):
            start, end = max(start, opening), min(end, closing)
            return (start, end) if end - start >= timedelta(minutes=30) else None

        story = []
        overdue = live(now - timedelta(hours=4), now - timedelta(hours=1, minutes=30))  # should be back already
        in_use = live(now - timedelta(hours=2), now + timedelta(hours=3))  # being used right now
        if overdue:
            story.append((by_tag["OSC-03"], "nikhil", *overdue, Booking.Status.CHECKED_OUT))
        if in_use and in_use[0] <= now < in_use[1]:
            story.append((by_tag["GPU-01"], "fatima", *in_use, Booking.Status.CHECKED_OUT))
        story += [
            # Waiting for the manager.
            (by_tag["3DP-01"], "aditya", at(1, 10), at(1, 15), Booking.Status.PENDING),
            (by_tag["GPU-02"], "zoya", at(1, 9), at(1, 17), Booking.Status.PENDING),
            (by_tag["3DP-02"], "fatima", at(2, 13), at(2, 17), Booking.Status.PENDING),
            (by_tag["GPU-01"], "fatima", at(3, 9), at(3, 16), Booking.Status.PENDING),
            (by_tag["3DP-01"], "aditya", at(4, 11), at(4, 18), Booking.Status.PENDING),
            # Upcoming approved bookings for the demo member.
            (by_tag["FPGA-03"], "fatima", at(1, 14), at(1, 17), Booking.Status.APPROVED),
            (by_tag["OSC-01"], "nikhil", at(2, 10), at(2, 12), Booking.Status.APPROVED),
            (by_tag["FPGA-01"], "nikhil", at(3, 14), at(3, 18), Booking.Status.APPROVED),
        ]
        for e, username, s, en, status in story:
            make(e, username, s, en, status)
        make(by_tag["GPU-02"], "nikhil", at(-3, 9), at(-3, 12), Booking.Status.REJECTED,
             note="GPU workstations need the usage-policy certification first - book an induction with Lakshmi.")

        # Background history: ~6 weeks past, ~10 days ahead.
        for day in range(-42, 11):
            date = today + timedelta(days=day)
            weekend = date.weekday() >= 5
            for e in equipment:
                if not e.bookable and day > -20:
                    continue  # broke ~3 weeks ago
                people = eligible(e)
                if not people:
                    continue
                for _ in range(rng.choice([0, 1, 1, 2] if not weekend else [0, 0, 1])):
                    hour = rng.choice(START_HOURS)
                    length = rng.randint(1, min(e.max_hours, 5, 20 - hour)) if hour < 20 else 0
                    if length <= 0:
                        continue
                    s = timezone.make_aware(datetime.combine(date, time(hour)), tz)
                    en = s + timedelta(hours=length)
                    available = [u for u in people if not overlaps(busy[u], s, en)]
                    if not free(e, s, en) or not available:
                        continue
                    if en <= now:
                        status = rng.choices(
                            [Booking.Status.RETURNED, Booking.Status.CANCELLED, Booking.Status.REJECTED],
                            weights=[86, 9, 5 if e.requires_approval else 0])[0]
                    elif s <= now:
                        status = Booking.Status.CHECKED_OUT
                    else:
                        status = Booking.Status.PENDING if (e.requires_approval and day <= 5 and rng.random() < 0.3) else Booking.Status.APPROVED
                    make(e, rng.choice(available), s, en, status,
                         note="Slot needed for a scheduled class lab." if status == Booking.Status.REJECTED else "")

        # A recent audit trail.
        recent = Booking.objects.filter(created_at__gte=now - timedelta(days=4)).select_related("equipment", "user")[:25]
        for b in recent:
            AuditLog.objects.create(actor=b.user, action="requested" if b.equipment.requires_approval else "booked",
                                    booking=b, equipment=b.equipment, detail=b.purpose)
        for b in Booking.objects.filter(decided_by=manager, decided_at__gte=now - timedelta(days=4)).select_related("equipment")[:15]:
            AuditLog.objects.create(actor=manager, action=b.status.replace("_", " "), booking=b, equipment=b.equipment,
                                    detail=b.manager_note)
        for log in AuditLog.objects.all():
            AuditLog.objects.filter(pk=log.pk).update(created_at=now - timedelta(minutes=rng.randint(5, 4 * 24 * 60)))

        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(users)} people, {len(equipment)} items, {Booking.objects.count()} bookings, "
            f"{Certification.objects.count()} certifications. Demo password: {DEMO_PASSWORD}"
        ))
