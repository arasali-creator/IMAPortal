from django import forms

from accounts.models import Employee, Team


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
