from django import forms
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from accounts.models import Employee, Team
from projects.models import Project


class ConsoleFileInput(forms.ClearableFileInput):
    """Clean replacement for Django's default file widget: an upload button
    plus a small "Remove" toggle, instead of the raw Currently/Clear/Change text."""

    def render(self, name, value, attrs=None, renderer=None):
        ctx = self.get_context(name, value, attrs)["widget"]
        attr_html = "".join(
            format_html(' {}="{}"', k, v) for k, v in ctx["attrs"].items() if v is not False
        )
        parts = [
            '<div class="cn-file-widget">',
            format_html(
                '<label class="cn-file-btn"><i class="fa-solid fa-upload"></i>'
                '<span class="cn-file-name">{}</span>'
                '<input type="file" name="{}"{}></label>',
                "Replace file" if ctx["is_initial"] else "Upload file",
                ctx["name"],
                mark_safe(attr_html),
            ),
        ]
        if ctx["is_initial"] and not self.is_required:
            parts.append(
                format_html(
                    '<label class="cn-file-clear"><input type="checkbox" name="{}" id="{}"><i class="fa-solid fa-trash-can"></i> Remove</label>',
                    ctx["checkbox_name"],
                    ctx["checkbox_id"],
                )
            )
        parts.append("</div>")
        return mark_safe("".join(parts))


class EmployeeCreateForm(forms.ModelForm):
    """Console counterpart of Django admin's add-employee form."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = Employee
        fields = ["cnic", "email", "full_name", "role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].initial = True

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class EmployeeEditForm(forms.ModelForm):
    new_password1 = forms.CharField(
        label="New Password",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Leave blank to keep the current password.",
    )
    new_password2 = forms.CharField(
        label="Confirm New Password",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Employee
        fields = [
            "cnic",
            "email",
            "full_name",
            "fathers_name",
            "date_of_birth",
            "gender",
            "marital_status",
            "contact_number",
            "residential_address",
            "date_of_joining",
            "reporting_manager_name",
            "department",
            "designation",
            "employment_type",
            "profile_picture",
            "cnic_front",
            "cnic_back",
            "degree_certificate",
            "father_cnic",
            "emergency_contact_name",
            "emergency_relationship",
            "emergency_contact_number",
            "emergency_contact_address",
            "blood_group",
            "previous_employer",
            "special_skills",
            "role",
            "is_active",
            "is_staff",
        ]
        widgets = {
            "residential_address": forms.Textarea(attrs={"rows": 2}),
            "emergency_contact_address": forms.Textarea(attrs={"rows": 2}),
            "previous_employer": forms.Textarea(attrs={"rows": 2}),
            "special_skills": forms.Textarea(attrs={"rows": 2}),
            "profile_picture": ConsoleFileInput,
            "cnic_front": ConsoleFileInput,
            "cnic_back": ConsoleFileInput,
            "degree_certificate": ConsoleFileInput,
            "father_cnic": ConsoleFileInput,
        }

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("new_password1"), cleaned.get("new_password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("new_password2", "Passwords do not match.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("new_password1"):
            user.set_password(self.cleaned_data["new_password1"])
        if commit:
            user.save()
        return user


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "project_manager", "members"]
        widgets = {
            "members": forms.CheckboxSelectMultiple,
        }


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            "name",
            "description",
            "upwork_profile_url",
            "upwork_profile_name",
            "hourly_rate_usd",
            "client_joined_date",
            "entries_required",
            "status",
            "members",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "client_joined_date": forms.DateInput(attrs={"type": "date"}),
            "members": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # PMs can only assign their own team members; admins can assign anyone.
        if user is not None and getattr(user, "role", None) == "pm":
            self.fields["members"].queryset = (
                Employee.objects.filter(role="employee", teams__project_manager=user)
                .distinct()
                .order_by("full_name", "email")
            )
        else:
            self.fields["members"].queryset = Employee.objects.filter(role="employee").order_by("full_name", "email")
