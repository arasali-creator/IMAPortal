from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.notify import notify

from .models import ExtraHoursRequest, Project, ProjectTimeLog


def _format_seconds(total):
    hours, rem = divmod(int(total), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m"


def _stop_log_within_budget(log, project):
    """End a running log, trimming the end time so the project never exceeds
    its hours budget. Returns True if the session was trimmed."""
    log.ended_at = timezone.now()
    budget = project.budget_seconds()
    trimmed = False
    if budget is not None:
        overshoot = project.total_seconds_logged() - budget
        if overshoot > 0:
            log.ended_at = max(
                log.started_at,
                log.ended_at - timedelta(seconds=overshoot),
            )
            trimmed = True
    log.save(update_fields=["ended_at"])
    return trimmed


def _budget_row(project, user):
    """Budget display data for one project card."""
    budget = project.budget_seconds()
    if budget is None:
        return {"has_budget": False}
    used = project.total_seconds_logged()
    remaining = max(0, budget - used)
    pct = min(100, round(used * 100 / budget)) if budget else 100
    pending = project.extra_hours_requests.filter(employee=user, status="pending").first()
    return {
        "has_budget": True,
        "budget_hours": project.allowed_hours,
        "used": _format_seconds(used),
        "remaining": _format_seconds(remaining),
        "remaining_seconds": remaining,
        "exhausted": remaining <= 0,
        "pct": pct,
        "pending_request": pending,
    }


@login_required
def my_projects(request):
    """Assigned projects for the logged-in employee, with a work timer per project.

    Deliberately excludes client-side details (rate, Upwork profile) — employees
    only see what they need: name, description, entries target, and their time.
    """
    projects = []
    qs = request.user.assigned_projects.filter(status="active").prefetch_related(
        "time_logs", "extra_hours_requests"
    )
    for project in qs:
        my_logs = [log for log in project.time_logs.all() if log.employee_id == request.user.id]
        running = next((log for log in my_logs if log.is_running), None)

        # A running timer that has eaten the whole budget gets stopped (trimmed) here.
        budget_left = project.remaining_seconds()
        if running and budget_left is not None and budget_left <= 0:
            _stop_log_within_budget(running, project)
            messages.warning(
                request,
                f"“{project.name}” reached its allowed hours — your timer was stopped. "
                "You can ask the project manager for extra hours below.",
            )
            notify(
                project.project_manager,
                f"Project “{project.name}” reached its hours budget",
                f"The allowed {project.allowed_hours}h have been fully logged. "
                f"{request.user.get_short_name()}'s running timer was stopped automatically.",
                url=f"/console/projects/{project.pk}/",
            )
            running = None

        seconds = sum(log.duration_seconds() for log in my_logs)
        projects.append({
            "obj": project,
            "running": running,
            "running_started_iso": running.started_at.isoformat() if running else "",
            "my_total": _format_seconds(seconds),
            "my_total_seconds": seconds,
            "sessions": len(my_logs),
            "budget": _budget_row(project, request.user),
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
        return redirect("projects:my_projects")

    remaining = project.remaining_seconds()
    if remaining is not None and remaining <= 0:
        messages.error(
            request,
            f"“{project.name}” has used all of its allowed {project.allowed_hours}h. "
            "Request extra hours from your project manager to continue.",
        )
        return redirect("projects:my_projects")

    ProjectTimeLog.objects.create(project=project, employee=request.user)
    messages.success(request, f"Timer started on “{project.name}”.")
    return redirect("projects:my_projects")


@login_required
@require_POST
def timer_stop(request, pk):
    project = get_object_or_404(Project, pk=pk, members=request.user)
    log = ProjectTimeLog.objects.filter(project=project, employee=request.user, ended_at__isnull=True).first()
    if log:
        trimmed = _stop_log_within_budget(log, project)
        messages.success(request, f"Timer stopped. Session: {_format_seconds(log.duration_seconds())}.")
        if trimmed:
            messages.warning(
                request,
                f"“{project.name}” hit its allowed hours during this session, so the "
                "extra time was not counted. Ask your project manager for more hours.",
            )
            notify(
                project.project_manager,
                f"Project “{project.name}” reached its hours budget",
                f"The allowed {project.allowed_hours}h have been fully logged.",
                url=f"/console/projects/{project.pk}/",
            )
    else:
        messages.error(request, "No running timer on this project.")
    return redirect("projects:my_projects")


@login_required
@require_POST
def request_extra_hours(request, pk):
    project = get_object_or_404(request.user.assigned_projects.filter(status="active"), pk=pk)

    if project.extra_hours_requests.filter(employee=request.user, status="pending").exists():
        messages.error(request, "You already have a pending extra-hours request on this project.")
        return redirect("projects:my_projects")

    try:
        hours = Decimal(request.POST.get("hours", "").strip())
    except (InvalidOperation, ValueError):
        hours = Decimal("0")
    if hours <= 0 or hours > Decimal("1000"):
        messages.error(request, "Enter a valid number of extra hours.")
        return redirect("projects:my_projects")

    reason = request.POST.get("reason", "").strip()
    ExtraHoursRequest.objects.create(project=project, employee=request.user, hours=hours, reason=reason)
    notify(
        project.project_manager,
        f"Extra hours requested on “{project.name}”",
        f"{request.user.get_short_name()} is asking for {hours}h more."
        + (f" Reason: {reason}" if reason else ""),
        url=f"/console/projects/{project.pk}/",
    )
    messages.success(request, f"Requested {hours}h extra on “{project.name}”. Your project manager has been notified.")
    return redirect("projects:my_projects")
