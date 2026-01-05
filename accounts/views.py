from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from .forms import EmployeeRegistrationForm, CNICLoginForm
from .models import Employee, PasswordResetRequest

@require_http_methods(["GET", "POST"])
def register(request):
    if request.method == 'POST':
        form = EmployeeRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return render(request, 'accounts/registration_submitted.html')
    else:
        form = EmployeeRegistrationForm()
    return render(request, 'accounts/register.html', {'form': form})

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.method == 'POST':
        form = CNICLoginForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user_object']
            if form.cleaned_data.get('inactive'):
                # stash CNIC in session for the pending view (no password stored)
                request.session['pending_cnic'] = user.cnic
                return redirect('pending')
            login(request, user)
            return redirect('dashboard')
    else:
        form = CNICLoginForm()
    return render(request, 'accounts/login.html', {'form': form})

def pending_view(request):
    cnic = request.session.get('pending_cnic')
    return render(request, 'accounts/pending.html', {'cnic': cnic})

@require_GET
def approval_status(request):
    """AJAX polling endpoint to check if a CNIC is approved"""
    cnic = request.GET.get('cnic')
    ok = False
    if cnic:
        ok = Employee.objects.filter(cnic=cnic, is_active=True).exists()
    return JsonResponse({'approved': ok})

@login_required
def dashboard(request):
    return render(request, 'accounts/dashboard.html')

def logout_view(request):
    logout(request)
    messages.success(request, 'Logged out successfully.')
    return redirect('login')

@require_http_methods(["GET", "POST"])
def reset_password_view(request):
    sent = False
    if request.method == "POST":
        identifier = request.POST.get("cnic_or_email", "").strip()
        if identifier:
            employee = Employee.objects.filter(cnic=identifier).first()
            if not employee:
                employee = Employee.objects.filter(email__iexact=identifier).first()
            PasswordResetRequest.objects.create(
                employee=employee,
                identifier=identifier,
            )
        sent = True
    return render(request, "accounts/reset_password.html", {"sent": sent})
