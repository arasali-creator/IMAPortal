# accounts/forms.py
from django import forms
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from .models import Employee, cnic_validator, alpha_spaces


class EmployeeRegistrationForm(forms.ModelForm):
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'})
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'})
    )

    class Meta:
        model = Employee
        fields = [
            # Personal
            'full_name', 'fathers_name', 'date_of_birth', 'gender', 'marital_status',
            'cnic', 'contact_number', 'email', 'residential_address',
            # Employment
            'date_of_joining',
            # Documents
            'profile_picture', 'cnic_front', 'cnic_back', 'degree_certificate', 'father_cnic',
            # Emergency
            'emergency_contact_name', 'emergency_relationship', 'emergency_contact_number', 'emergency_contact_address',
            # Additional
            'blood_group',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'date_of_joining': forms.DateInput(attrs={'type': 'date'}),
            'residential_address': forms.Textarea(attrs={'rows': 3, 'maxlength': 250}),
            'emergency_contact_address': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_full_name(self):
        v = self.cleaned_data['full_name']
        alpha_spaces(v)
        return v

    def clean_fathers_name(self):
        v = self.cleaned_data['fathers_name']
        alpha_spaces(v)
        return v

    def clean_cnic(self):
        cnic = self.cleaned_data['cnic']
        cnic_validator(cnic)
        return cnic

    def clean_contact_number(self):
        num = self.cleaned_data['contact_number']
        if num and len(num) != 11:
            raise ValidationError("Contact number must be exactly 11 digits.")
        return num

    def clean_emergency_contact_number(self):
        num = self.cleaned_data['emergency_contact_number']
        if num and len(num) != 11:
            raise ValidationError("Emergency contact number must be exactly 11 digits.")
        return num

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if Employee.objects.filter(email=email).exists():
            raise ValidationError('This email is already registered.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Passwords do not match.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        # ensure pending until admin approval
        user.is_active = False
        if commit:
            user.save()
        return user

class CNICLoginForm(forms.Form):
    cnic = forms.CharField(
        label='CNIC (13 digits)',
        widget=forms.TextInput(attrs={'placeholder': 'Enter your CNIC'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Enter your password'})
    )

    error_messages = {
        'invalid_cnic': 'No account found with this CNIC.',
        'invalid_password': 'Incorrect password.',
        'inactive': 'Your account is pending admin approval.',
    }

    def clean_cnic(self):
        cnic = self.cleaned_data.get('cnic')
        if not Employee.objects.filter(cnic=cnic).exists():
            raise forms.ValidationError(self.error_messages['invalid_cnic'])
        return cnic

    def clean_password(self):
        # we validate password later with authenticate
        password = self.cleaned_data.get('password')
        if not password:
            raise forms.ValidationError("Password is required.")
        return password

    def clean(self):
        cleaned = super().clean()
        cnic = cleaned.get('cnic')
        password = cleaned.get('password')

        if cnic and password:
            user = authenticate(username=cnic, password=password)

            if user is None:
                # user exists (checked above) but password is wrong
                raise forms.ValidationError(self.error_messages['invalid_password'])

            if not user.is_active:
                cleaned['user_object'] = user
                cleaned['inactive'] = True
                return cleaned

            # active user
            cleaned['user_object'] = user
            cleaned['inactive'] = False
            return cleaned

        return cleaned