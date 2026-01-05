from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator, EmailValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date
import os

# ---------- Validators ----------
alpha_spaces = RegexValidator(regex=r'^[A-Za-z ]+$', message='Only alphabets and spaces are allowed.')
cnic_validator = RegexValidator(regex=r'^\d{13}$', message='CNIC must be exactly 13 digits.')

email_validator = EmailValidator(message='Enter a valid email.')

def ensure_18_plus(value: date):
    if not value:
        return
    today = timezone.localdate()
    age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    if age < 18:
        raise ValidationError('Age must be 18 or above.')

def validate_image_max_2mb(image):
    """Validate image size (max 2 MB)."""
    filesize = image.file.size
    megabyte_limit = 2
    if filesize > megabyte_limit * 1024 * 1024:
        raise ValidationError(f"Max file size is {megabyte_limit}MB")

def validate_degree_max_5mb_and_type(file):
    """Validate uploaded degree file size (<= 5MB) and allowed types."""
    filesize = file.size
    megabyte_limit = 5
    if filesize > megabyte_limit * 1024 * 1024:
        raise ValidationError(f"Max file size is {megabyte_limit}MB")

    # Allowed extensions
    valid_extensions = ['.jpg', '.jpeg', '.png', '.pdf']
    ext = os.path.splitext(file.name)[1].lower()

    if ext not in valid_extensions:
        raise ValidationError(f"Unsupported file type. Allowed: {', '.join(valid_extensions)}")

# ---------- File upload helpers ----------
def upload_to(instance, filename, folder):
    cnic = getattr(instance, 'cnic', None) or getattr(getattr(instance, 'user', None), 'username', 'unknown')
    return f'employees/{cnic}/{folder}/{filename}'

def profile_picture_path(instance, filename): return upload_to(instance, filename, 'profile')
def cnic_front_path(instance, filename): return upload_to(instance, filename, 'cnic_front')
def cnic_back_path(instance, filename): return upload_to(instance, filename, 'cnic_back')
def degree_path(instance, filename): return upload_to(instance, filename, 'degree')
def father_cnic_path(instance, filename): return upload_to(instance, filename, 'father_cnic')

# ---------- Custom manager ----------
class EmployeeManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, cnic, email, password=None, **extra_fields):
        if not cnic:
            raise ValueError('The CNIC must be set')
        if not email:
            raise ValueError('An email is required')
        email = self.normalize_email(email)
        user = self.model(cnic=cnic, email=email, **extra_fields)
        user.set_password(password)
        if 'is_active' not in extra_fields:
            user.is_active = False
        user.save(using=self._db)
        return user

    def create_superuser(self, cnic, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(cnic, email, password, **extra_fields)

    class Media:
        css = {"all": ("css/admin/accounts.css",)}
# ---------- User model ----------
class Employee(AbstractBaseUser, PermissionsMixin):
    cnic = models.CharField(max_length=13, unique=True, validators=[cnic_validator])
    email = models.EmailField(unique=True, validators=[email_validator])

    # 1. Personal
    full_name = models.CharField(max_length=120, blank=True, null=True, validators=[alpha_spaces])
    fathers_name = models.CharField(max_length=120, blank=True, null=True, validators=[alpha_spaces])
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, choices=[('male','Male'),('female','Female'),('other','Other'),('na','Prefer not to say')], blank=True, null=True)
    marital_status = models.CharField(max_length=10, choices=[('single','Single'),('married','Married'),('divorced','Divorced'),('widowed','Widowed')], blank=True, null=True)
    contact_number = models.CharField(max_length=14, blank=True, null=True)
    residential_address = models.TextField(max_length=250, blank=True, null=True)

    # 2. Employment
    date_of_joining = models.DateField(blank=True, null=True)
    reporting_manager_name = models.CharField(max_length=120, blank=True, null=True, validators=[alpha_spaces])
    department = models.CharField(max_length=10, choices=[('HR','HR'),('IT','IT'),('FIN','Finance'),('OPS','Operations'),('SALES','Sales'),('OTHER','Other')], blank=True, null=True)
    designation = models.CharField(max_length=120, blank=True, null=True)
    employment_type = models.CharField(max_length=2, choices=[('FT','Full-time'),('PT','Part-time'),('CT','Contract'),('IN','Internship')], blank=True, null=True)
    employee_code = models.CharField(max_length=20, unique=True, blank=True, null=True)

    # 3. Documents
    profile_picture = models.ImageField(upload_to=profile_picture_path, validators=[], blank=True, null=True)
    cnic_front = models.ImageField(upload_to=cnic_front_path, validators=[], blank=True, null=True)
    cnic_back = models.ImageField(upload_to=cnic_back_path, validators=[], blank=True, null=True)
    degree_certificate = models.FileField(upload_to=degree_path, validators=[], blank=True, null=True)
    father_cnic = models.ImageField(upload_to=father_cnic_path, validators=[], blank=True, null=True)

    # 4. Emergency
    emergency_contact_name = models.CharField(max_length=120, blank=True, null=True)
    emergency_relationship = models.CharField(max_length=10, choices=[('father','Father'),('mother','Mother'),('spouse','Spouse'),('sibling','Sibling'),('friend','Friend'),('other','Other')], blank=True, null=True)
    emergency_contact_number = models.CharField(max_length=14, blank=True, null=True)
    emergency_contact_address = models.TextField(blank=True, null=True)

    # 5. Optional extras
    blood_group = models.CharField(max_length=3, choices=[('A+','A+'),('A-','A-'),('B+','B+'),('B-','B-'),('O+','O+'),('O-','O-'),('AB+','AB+'),('AB-','AB-')], blank=True, null=True)
    previous_employer = models.TextField(blank=True, null=True)
    special_skills = models.TextField(blank=True, null=True)

    # Roles
    ROLE_CHOICES = [
        ('employee', 'Employee'),
        ('pm', 'Project Manager'),
        ('admin', 'Admin (CEO)'),   # 🔹 added Admin role
    ]
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='employee',
        help_text="Role of the employee. Default is 'Employee'."
    )

    # Admin flags
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = EmployeeManager()

    USERNAME_FIELD = 'cnic'
    REQUIRED_FIELDS = ['email']

    def __str__(self):
        return f'{self.full_name or self.email or self.cnic}'
    
    def generate_employee_code(self):
        year = timezone.now().year
        prefix = f'EMP-{year}-'
        last = Employee.objects.filter(employee_code__startswith=prefix).order_by('employee_code').last()
        if last and last.employee_code and last.employee_code.split('-')[-1].isdigit():
            nxt = int(last.employee_code.split('-')[-1]) + 1
        else:
            nxt = 1
        return f'{prefix}{nxt:04d}'

    def save(self, *args, **kwargs):
        if not self.employee_code:
            self.employee_code = self.generate_employee_code()
        super().save(*args, **kwargs)
    class Media:
        css = {"all": ("css/admin/accounts.css",)}
    def get_full_name(self):
        return self.full_name or self.email or str(self)

    def get_short_name(self):
        # what you want to show in top bar (name)
        return (self.full_name.split(" ")[0] if self.full_name else (self.email or str(self)))


class PasswordResetRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("resolved", "Resolved"),
    ]

    employee = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name="password_reset_requests"
    )
    identifier = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.identifier} ({self.status})"


class Notification(models.Model):
    log_entry_id = models.PositiveIntegerField(unique=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications"
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.TextField(blank=True, null=True)
    object_repr = models.CharField(max_length=200)
    action_flag = models.PositiveSmallIntegerField()
    change_message = models.TextField(blank=True)
    action_time = models.DateTimeField()
    url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-action_time"]

    def __str__(self):
        return f"{self.object_repr} ({self.action_time:%Y-%m-%d %H:%M})"

# ---------- Team model ----------
class Team(models.Model):
    name = models.CharField(max_length=150)
    project_manager = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="managed_teams",
        limit_choices_to={'role': 'pm'}
    )
    members = models.ManyToManyField(
        Employee,
        related_name="teams",
        blank=True,
        limit_choices_to={'role': 'employee'}
    )

    def __str__(self):
        return f"{self.name} (PM: {self.project_manager.full_name})"

    def clean(self):
        """
        Enforce that only Admin can assign employees to any PM,
        but a PM can only assign employees to their own team.
        """
        if hasattr(self, "_request") and self._request.user.role == "pm":
            if self.project_manager != self._request.user:
                raise ValidationError("You can only manage your own team.")
