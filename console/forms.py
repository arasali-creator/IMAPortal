from django import forms

from accounts.models import Employee, Team


class EmployeeEditForm(forms.ModelForm):
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


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "project_manager", "members"]
        widgets = {
            "members": forms.CheckboxSelectMultiple,
        }
