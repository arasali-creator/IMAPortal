from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Employee
from upwork.models import UpworkJobEntry, UpworkProfile, UpworkSetting


def make_user(cnic, email, role):
    user = Employee.objects.create_user(cnic=cnic, email=email, password="pass12345", is_active=True)
    user.role = role
    user.save()
    return user


class UpworkTrackingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("1111111111111", "admin@test.com", "admin")
        cls.pm1 = make_user("2222222222222", "pm1@test.com", "pm")
        cls.pm2 = make_user("3333333333333", "pm2@test.com", "pm")
        cls.employee = make_user("4444444444444", "emp@test.com", "employee")

    def login(self, user):
        self.client.force_login(user)

    def test_admin_sets_rate_and_creates_profile(self):
        self.login(self.admin)
        resp = self.client.post(reverse("console:upwork_profiles"), {"action": "update_rate", "connect_rate": "0.20"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(UpworkSetting.current_rate(), Decimal("0.20"))

        resp = self.client.post(
            reverse("console:upwork_profiles"),
            {"action": "create_profile", "name": "Profile A", "pm_id": self.pm1.id},
        )
        self.assertEqual(resp.status_code, 302)
        profile = UpworkProfile.objects.get(name="Profile A")
        self.assertEqual(profile.project_manager, self.pm1)

    def test_pm_cannot_open_profiles_page(self):
        self.login(self.pm1)
        resp = self.client.get(reverse("console:upwork_profiles"))
        self.assertEqual(resp.status_code, 403)

    def test_employee_cannot_open_tracking(self):
        self.login(self.employee)
        resp = self.client.get(reverse("console:upwork_tracking"))
        self.assertEqual(resp.status_code, 403)

    def test_entry_amount_uses_rate_snapshot(self):
        UpworkSetting.objects.create(connect_rate=Decimal("0.20"))
        profile = UpworkProfile.objects.create(name="P1", project_manager=self.pm1)

        self.login(self.pm1)
        resp = self.client.post(
            reverse("console:upwork_entry_create"),
            {
                "profile": profile.id,
                "date": "2026-07-14",
                "jobs_applied": 5,
                "proposal_views": 3,
                "responses": 2,
                "offers": 1,
                "hired": 1,
                "connects_used": 40,
            },
        )
        self.assertEqual(resp.status_code, 302)
        entry = UpworkJobEntry.objects.get(profile=profile)
        self.assertEqual(entry.connect_rate, Decimal("0.20"))
        self.assertEqual(entry.amount_spent, Decimal("8.00"))
        self.assertEqual(entry.created_by, self.pm1)

        # Admin raises the rate — the old entry must not change.
        setting = UpworkSetting.objects.first()
        setting.connect_rate = Decimal("0.50")
        setting.save()
        entry.refresh_from_db()
        self.assertEqual(entry.amount_spent, Decimal("8.00"))

        # Editing the entry recomputes with the snapshotted rate, not the new one.
        resp = self.client.post(
            reverse("console:upwork_entry_edit", args=[entry.pk]),
            {
                "profile": profile.id,
                "date": "2026-07-14",
                "jobs_applied": 5,
                "proposal_views": 3,
                "responses": 2,
                "offers": 1,
                "hired": 1,
                "connects_used": 50,
            },
        )
        self.assertEqual(resp.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.connect_rate, Decimal("0.20"))
        self.assertEqual(entry.amount_spent, Decimal("10.00"))

        # A brand-new entry picks up the new rate.
        self.client.post(
            reverse("console:upwork_entry_create"),
            {
                "profile": profile.id,
                "date": "2026-07-15",
                "jobs_applied": 1,
                "proposal_views": 0,
                "responses": 0,
                "offers": 0,
                "hired": 0,
                "connects_used": 10,
            },
        )
        new_entry = UpworkJobEntry.objects.get(profile=profile, date=date(2026, 7, 15))
        self.assertEqual(new_entry.connect_rate, Decimal("0.50"))
        self.assertEqual(new_entry.amount_spent, Decimal("5.00"))

    def test_one_entry_per_profile_per_date(self):
        profile = UpworkProfile.objects.create(name="P1", project_manager=self.pm1)
        UpworkJobEntry.objects.create(profile=profile, date=date(2026, 7, 14), connects_used=5)

        self.login(self.pm1)
        resp = self.client.post(
            reverse("console:upwork_entry_create"),
            {
                "profile": profile.id,
                "date": "2026-07-14",
                "jobs_applied": 1,
                "proposal_views": 0,
                "responses": 0,
                "offers": 0,
                "hired": 0,
                "connects_used": 1,
            },
        )
        self.assertEqual(resp.status_code, 200)  # form redisplayed with error
        self.assertContains(resp, "already exists")
        self.assertEqual(UpworkJobEntry.objects.filter(profile=profile).count(), 1)

    def test_pm_only_sees_own_profiles(self):
        p1 = UpworkProfile.objects.create(name="PM1 Profile", project_manager=self.pm1)
        p2 = UpworkProfile.objects.create(name="PM2 Profile", project_manager=self.pm2)
        UpworkJobEntry.objects.create(profile=p1, date=date(2026, 7, 14), jobs_applied=7, connects_used=10)
        e2 = UpworkJobEntry.objects.create(profile=p2, date=date(2026, 7, 14), jobs_applied=9, connects_used=20)

        self.login(self.pm1)
        resp = self.client.get(reverse("console:upwork_tracking"))
        self.assertContains(resp, "PM1 Profile")
        self.assertNotContains(resp, "PM2 Profile")

        # PM1 cannot log against, edit, or delete PM2's data.
        form_resp = self.client.post(
            reverse("console:upwork_entry_create"),
            {
                "profile": p2.id,
                "date": "2026-07-13",
                "jobs_applied": 1,
                "proposal_views": 0,
                "responses": 0,
                "offers": 0,
                "hired": 0,
                "connects_used": 1,
            },
        )
        self.assertEqual(form_resp.status_code, 200)
        self.assertFalse(UpworkJobEntry.objects.filter(profile=p2, date=date(2026, 7, 13)).exists())
        self.assertEqual(self.client.get(reverse("console:upwork_entry_edit", args=[e2.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("console:upwork_entry_delete", args=[e2.pk])).status_code, 404)

        # Admin sees both profiles.
        self.login(self.admin)
        resp = self.client.get(reverse("console:upwork_tracking"))
        self.assertContains(resp, "PM1 Profile")
        self.assertContains(resp, "PM2 Profile")

    def test_breakdown_views_render(self):
        profile = UpworkProfile.objects.create(name="P1", project_manager=self.pm1)
        UpworkJobEntry.objects.create(profile=profile, date=date(2026, 7, 14), jobs_applied=3, connects_used=12)
        UpworkJobEntry.objects.create(profile=profile, date=date(2026, 6, 1), jobs_applied=2, connects_used=8)
        UpworkJobEntry.objects.create(profile=profile, date=date(2025, 12, 31), jobs_applied=1, connects_used=4)

        self.login(self.admin)
        for view in ("daily", "weekly", "monthly", "yearly"):
            resp = self.client.get(reverse("console:upwork_tracking"), {"view": view, "year": 2026, "month": 7})
            self.assertEqual(resp.status_code, 200, view)

        # Yearly view spans all years.
        resp = self.client.get(reverse("console:upwork_tracking"), {"view": "yearly"})
        self.assertContains(resp, "2025")
        self.assertContains(resp, "2026")

    def test_profile_filter(self):
        p1 = UpworkProfile.objects.create(name="Alpha", project_manager=self.pm1)
        p2 = UpworkProfile.objects.create(name="Beta", project_manager=self.pm2)
        UpworkJobEntry.objects.create(profile=p1, date=date(2026, 7, 14), connects_used=10)
        UpworkJobEntry.objects.create(profile=p2, date=date(2026, 7, 14), connects_used=20)

        self.login(self.admin)
        resp = self.client.get(reverse("console:upwork_tracking"), {"view": "daily", "year": 2026, "month": 7, "profile": p1.id})
        self.assertEqual(resp.context["totals"]["connects_used"], 10)
