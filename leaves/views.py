from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import LeaveRequest
from .forms import LeaveRequestForm
from accounts.models import Team

@login_required
def my_leave_requests(request):
    """
    Employee view: submit new leave and see history.
    PMs see leaves of their team members.
    """
    employee = request.user  # request.user is already an Employee instance

    # Handle new leave submission
    if request.method == "POST":
        form = LeaveRequestForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.employee = employee
            leave.pm_status = "Pending"
            leave.admin_status = "Pending"
            leave.status = "Pending"   # Final status defaults to Pending
            leave.save()
            return redirect("my_leave_requests")
    else:
        form = LeaveRequestForm()

    # Determine leaves to show
    if getattr(employee, "role", None) == "pm":
        try:
            team = Team.objects.get(project_manager=employee)
            leaves = LeaveRequest.objects.filter(employee__in=team.members.all()).order_by("-created_at")
        except Team.DoesNotExist:
            leaves = LeaveRequest.objects.none()
    else:
        # Normal employee sees only their own leaves
        leaves = LeaveRequest.objects.filter(employee=employee).order_by("-created_at")

    # Update final status dynamically
    for leave in leaves:
        if leave.pm_status == "Approved" or leave.admin_status == "Approved":
            leave.status = "Approved"
        elif leave.pm_status == "Rejected" or leave.admin_status == "Rejected":
            leave.status = "Rejected"
        else:
            leave.status = "Pending"

    context = {
        "form": form,
        "leaves": leaves,
    }
    return render(request, "leave/my_requests.html", context)
