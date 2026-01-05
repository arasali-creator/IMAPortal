# leaves/models.py
from django.db import models
from accounts.models import Employee
from datetime import date
from django.utils import timezone


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    reason = models.TextField(default="No reason provided")
    start_date = models.DateField(default=date.today)
    end_date = models.DateField(default=date.today)
    pm_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    admin_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')  # final status
    created_at = models.DateTimeField(auto_now_add=True)  # ✅ no default
    updated_at = models.DateTimeField(auto_now=True)      # ✅ no default

    def __str__(self):
        return f"{self.employee.full_name} | {self.start_date} → {self.end_date}"
