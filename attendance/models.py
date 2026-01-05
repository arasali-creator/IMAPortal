# attendance/models.py
from django.db import models
from django.utils import timezone

class Attendance(models.Model):
    employee = models.ForeignKey("accounts.Employee", on_delete=models.CASCADE)
    check_in = models.DateTimeField()
    check_out = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.employee.full_name} - {self.check_in.date()}"
    @property
    def hours_worked(self):
        if self.check_in and self.check_out:
            delta = self.check_out - self.check_in
            return round(delta.total_seconds() / 3600, 2)  # hours
        return 0
