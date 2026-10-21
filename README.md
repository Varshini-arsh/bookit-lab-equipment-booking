# BookIt: lab equipment booking system

BookIt replaces the paper sign-up sheet on a shared lab's door. Members see what's free right now, drag across a week calendar to book a slot, and get instant feedback when a slot clashes, runs past opening hours or needs a safety certification. Lab managers approve requests, hand items over at the desk, track overdue returns and see how the equipment is actually used.

**Stack:** Python · Django 5 · Django REST Framework · MySQL (SQLite fallback) · HTML/CSS/vanilla JavaScript · Chart.js

---

## Case study

The demo data models a university **electronics & computing lab** shared by four departments (ECE, CSE, Mechanical, Physics). It has 13 items in 5 categories:

| Category | Items | Rules |
|---|---|---|
| Oscilloscopes | Keysight DSOX1204G ×2, Rigol DS1054Z | Open to all, instant booking |
| FPGA Boards | Basys 3 ×2, PYNQ-Z2, Nexys A7 (out for repair) | Open to all, instant booking |
| 3D Printers | Prusa MK4, Formlabs Form 3 | **Safety certification** + manager approval |
| GPU Workstations | RTX 4090, 2× RTX A6000 | **Usage-policy certification** + manager approval |
| Soldering Stations | Weller, Hakko | **Safety certification** |

The seed also generates about 6 weeks of booking history, so the reports have real patterns to show (busy late mornings, quiet weekends).

**The problems it solves**
1. **Double bookings.** Two students would turn up for the same oscilloscope. BookIt rejects any overlapping interval, both in the database query and live in the UI.
2. **Unsafe use.** Untrained students used the resin printer. Restricted categories need a valid (unexpired) certification before booking.
3. **Items not coming back.** Checked-out items past their end time are flagged as overdue for the manager and for the member.
4. **No usage data for budget requests.** Reports show utilisation, the most-used items, usage by department and peak hours, plus a CSV export.

## Features

| Area | What you can do |
|---|---|
| Catalog | Live status on every card (Available now, In use until 15:30 by Fatima, Out of service), category filters, "available now" toggle, search from the top bar (press `/`) |
| Week calendar | **Drag to select** a slot (pointer events work for mouse and touch, 30-minute snapping), shaded past slots, a "now" line, colour-coded bookings (yours, others', pending), hover tooltips, week navigation |
| Live check | While you choose a slot, `/api/bookings/check/` returns every problem at once: overlap, opening hours, max duration, certification, out of service |
| My bookings | Upcoming, past and all, cancel before the slot starts, the manager's rejection reason, overdue flag |
| Approvals (manager) | A request queue with Approve and Reject (quick-reason chips), the desk view for check-out and return, overdue returns at the top |
| Reports (manager) | 7/30/90-day window, stat tiles, bookings per day, most-used equipment, **peak-hours heatmap**, usage by department, booking outcomes, **CSV export** |
| Certifications | Members see their status. Managers get a member × category matrix with one-click grant (1 year) and revoke |
| Audit log | Who did what, and when: requests, approvals, check-outs, certification changes |
| Global | Dark mode, toasts, loading skeletons, responsive layout, keyboard access |

## Booking rules (`core/services.py`)

One function, `booking_problems()`, is used by the create endpoint, the live check endpoint and the tests:

- The end must be after the start, the slot can't be in the past, and bookings open at most 60 days ahead
- Same day only, within lab hours **08:00–20:00**
- Duration ≤ the item's `max_hours`
- The item must be in service
- A valid certification for restricted categories
- **No overlap** with pending, approved or checked-out bookings of the same item

```python
# Two intervals overlap when each starts before the other ends.
# Back-to-back bookings (10:00-12:00 then 12:00-14:00) are allowed.
Booking.objects.filter(equipment=equipment, status__in=Booking.ACTIVE,
                       start__lt=end, end__gt=start)
```

A composite index on `(equipment, start, end)` keeps this query fast as the history grows.

### Booking lifecycle

```
            ┌── open item ──► APPROVED ──► CHECKED_OUT ──► RETURNED
request ────┤                    ▲    (desk, ≤30 min before start)
            └── restricted ─► PENDING ──► REJECTED (reason required)
                                  │
              PENDING / APPROVED ─┴──► CANCELLED (member before start, or manager)
```

### A hand-written SQL report

Usage by department joins bookings, users and profiles:

```sql
SELECT p.department,
       COUNT(b.id)               AS bookings,
       COUNT(DISTINCT b.user_id) AS people
FROM core_booking b
JOIN auth_user u    ON u.id = b.user_id
JOIN core_profile p ON p.user_id = u.id
WHERE b.start >= %s AND b.start < %s
  AND b.status IN ('approved', 'checked_out', 'returned')
GROUP BY p.department
ORDER BY bookings DESC;
```

Hours per item use an ORM `Sum(F("end") - F("start"))`, which Django translates for both SQLite and MySQL.

## Data model

```
User 1─1 Profile(role: member|manager, department)
Category(requires_certification) 1─* Equipment(asset_tag, condition, requires_approval, max_hours)
User *─* Category  through Certification(granted_by, expires_on)
Equipment 1─* Booking(user, start, end, status, purpose, manager_note, decided_by, checked_out_at, returned_at)
AuditLog(actor, action, booking, equipment, detail)
```

## REST API

Every endpoint requires a session login. You can browse them at `/api/`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/me/` | Profile, certifications, counts (upcoming, pending, overdue) |
| GET | `/api/categories/` | Categories with item counts |
| GET | `/api/equipment/` | Catalog with live `current` and `next_booking`. `?category=`, `?search=`, `?available=1` |
| GET | `/api/equipment/{id}/schedule/?start=YYYY-MM-DD&days=7` | Bookings for the calendar |
| GET/POST | `/api/bookings/` | Your bookings (`?scope=all` for managers), `?when=upcoming\|past\|today`, `?status=` |
| GET | `/api/bookings/check/?equipment=&start=&end=` | Live validation: `{ok, problems[], hours, requires_approval}` |
| POST | `/api/bookings/{id}/approve\|reject\|cancel\|checkout\|return/` | Lifecycle transitions (reject needs `{note}`) |
| GET/POST/DELETE | `/api/certifications/` | Members see their own. Managers grant and revoke |
| GET | `/api/reports/summary/?days=30` | Manager dashboard data |
| GET | `/api/reports/export.csv?days=30` | CSV download |
| GET | `/api/audit/` | Latest 100 audit entries (manager) |

## Run it locally

```bash
git clone https://github.com/Varshini-arsh/bookit-lab-equipment-booking.git
cd bookit-lab-equipment-booking
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo       # loads the shared-lab case study
python manage.py runserver
```

Open http://127.0.0.1:8000 and click a **demo account**. Each one shows a different side of the app:

| Account | Shows |
|---|---|
| **Lakshmi Krishnan**, lab manager | Approvals queue, desk check-out and return, reports, certification matrix, audit log |
| **Fatima Sheikh**, PhD scholar | Certified for GPUs and 3D printers, so she can request restricted items |
| **Nikhil Verma**, B.Tech student | No certifications (restricted items are locked), one overdue return, one rejected request |

All demo passwords are `demo12345`.

### Use MySQL instead of SQLite

```bash
docker compose up -d                       # MySQL 8.4 on localhost:3307
# PowerShell
$env:DB_ENGINE="mysql"; python manage.py migrate; python manage.py seed_demo; python manage.py runserver
# bash
DB_ENGINE=mysql python manage.py migrate && DB_ENGINE=mysql python manage.py seed_demo
```

The connection settings are `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` and `DB_PORT` (see `.env.example`). The driver is PyMySQL, which is pure Python.

## Tests

```bash
python manage.py test core.tests
```

There are 15 API tests: overlap versus back-to-back bookings, cancellation freeing a slot, opening hours and max duration, out-of-service items, certification required or expired, manager-only actions, reject-needs-a-reason, the full approve → checkout → return lifecycle, privacy between members, the live check endpoint, and report numbers plus the CSV export.

## Project structure

```
bookit/             settings (env-driven), urls
core/
  models.py         Profile, Category, Equipment, Certification, Booking, AuditLog
  services.py       booking rules: conflicts, hours, certification
  serializers.py    DRF serializers (validation calls services)
  views.py          ViewSets, lifecycle actions, schedule, reports (ORM + raw SQL), CSV
  pages.py          login, demo login, app shell
  tests.py          API tests
  management/commands/seed_demo.py
templates/          login.html, app.html, icons.html
static/css/         app.css (design tokens, shared components), bookit.css (calendar, heatmap, cards)
static/js/app.js    SPA: router, catalog, drag-to-book calendar, approvals, reports
```
