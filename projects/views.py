from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Project, ProjectTimeLog


def _format_seconds(total):
    hours, rem = divmod(int(total), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m"


@login_required
def my_projects(request):
    """Assigned projects for the logged-in employee, with a work timer per project.

    Deliberately excludes client-side details (rate, Upwork profile) — employees
    only see what they need: name, description, entries target, and their time.
    """
    projects = []
    for project in request.user.assigned_projects.filter(status="active").prefetch_related("time_logs"):
        my_logs = [log for log in project.time_logs.all() if log.employee_id == request.user.id]
        running = next((log for log in my_logs if log.is_running), None)
        seconds = sum(log.duration_seconds() for log in my_logs)
        projects.append({
            "obj": project,
            "running": running,
            "running_started_iso": running.started_at.isoformat() if running else "",
            "my_total": _format_seconds(seconds),
            "my_total_seconds": seconds,
            "sessions": len(my_logs),
        })
    return render(request, "projects/my_projects.html", {"projects": projects})


@login_required
@require_POST
def timer_start(request, pk):
    project = get_object_or_404(request.user.assigned_projects.filter(status="active"), pk=pk)
    # One running timer per employee across all projects.
    already = ProjectTimeLog.objects.filter(employee=request.user, ended_at__isnull=True).select_related("project").first()
    if already:
        messages.error(request, f"You already have a running timer on “{already.project.name}”. Stop it first.")
    else:
        ProjectTimeLog.objects.create(project=project, employee=request.user)
        messages.success(request, f"Timer started on “{project.name}”.")
    return redirect("projects:my_projects")


@login_required
@require_POST
def timer_stop(request, pk):
    project = get_object_or_404(Project, pk=pk, members=request.user)
    log = ProjectTimeLog.objects.filter(project=project, employee=request.user, ended_at__isnull=True).first()
    if log:
        log.ended_at = timezone.now()
        log.save(update_fields=["ended_at"])
        messages.success(request, f"Timer stopped. Session: {_format_seconds(log.duration_seconds())}.")
    else:
        messages.error(request, "No running timer on this project.")
    return redirect("projects:my_projects")
