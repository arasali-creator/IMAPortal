import os
from pathlib import Path

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
DEBUG = os.environ.get("DEBUG", "True") == "True"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get(
        "ALLOWED_HOSTS", "arasali.pythonanywhere.com,localhost,127.0.0.1"
    ).split(",")
    if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

INSTALLED_APPS = [
    "daphne",
    "channels",
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "attendance",
    "leaves",
    "console",
    "projects",
    "payroll.apps.PayrollConfig",
    "django.contrib.humanize",
        # ✅ Slick Reporting
    "slick_reporting",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "office_portal.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "builtins": ["accounts.templatetags.safe_get"],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "office_portal.wsgi.application"
ASGI_APPLICATION = "office_portal.asgi.application"

# MariaDB/MySQL when DB_NAME is set in .env; falls back to SQLite otherwise.
if os.environ.get("DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ["DB_NAME"],
            "USER": os.environ.get("DB_USER", "root"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Custom user that logs in with CNIC
AUTH_USER_MODEL = "accounts.Employee"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Email (Hostinger SMTP) — set EMAIL_HOST_USER/EMAIL_HOST_PASSWORD via .env, never hardcode here
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.hostinger.com")
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
    EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "True") == "True"
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "False") == "True"
    DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# =======================
# UNFOLD THEME + SIDEBAR
# =======================
UNFOLD = {
    "SITE_TITLE": "Office Portal",
    "SITE_HEADER": "Office Portal",
    "SITE_LOGO": "/static/images/logo.png",

    # ✅ custom admin css file (create: static/css/styles.css)
    "STYLES": ["css/styles.css"],

    "SITE_DROPDOWN": [
        {
            "icon": "diamond",
            "title": _("Visit IMA Sales Solutions"),
            "link": "https://imasalessolutions.com/",
        },
    ],

    "BORDER_RADIUS": "12px",

    # ✅ Primary: #ff6600, Secondary/Base: #181818
    "COLORS": {
        "base": {
            "50":  "#f5f5f5",
            "100": "#e5e5e5",
            "200": "#d4d4d4",
            "300": "#a3a3a3",
            "400": "#737373",
            "500": "#525252",
            "600": "#404040",
            "700": "#262626",
            "800": "#1f1f1f",
            "900": "#181818",
            "950": "#0f0f0f",
        },
        "primary": {
            "50":  "#fff2e6",
            "100": "#ffe0cc",
            "200": "#ffc299",
            "300": "#ffa366",
            "400": "#ff8533",
            "500": "#ff6600",
            "600": "#e65c00",
            "700": "#cc5200",
            "800": "#b34700",
            "900": "#993d00",
            "950": "#662800",
        },
        "font": {
            "subtle-light": "var(--color-base-600)",
            "subtle-dark": "var(--color-base-400)",
            "default-light": "var(--color-base-800)",
            "default-dark": "var(--color-base-100)",
            "important-light": "var(--color-base-950)",
            "important-dark": "white",
        },
    },

    "SIDEBAR": {
        "show_search": False,
        "command_search": False,
        "show_all_applications": False,
        "navigation": [
            {
                "items": [
                    {
                        "title": _("Employee"),
                        "icon": "people",
                        "link": reverse_lazy("admin:accounts_employee_changelist"),
                        "permission": "accounts.utils.can_view_employees",
                    },
                    {
                        "title": _("Teams"),
                        "icon": "diversity_3",
                        "link": reverse_lazy("admin:accounts_team_changelist"),
                        "permission": "accounts.utils.can_view_teams",
                    },
                    {
                        "title": _("Attendance"),
                        "icon": "check_in_out",
                        "link": reverse_lazy("admin:attendance_attendance_changelist"),
                        "permission": "accounts.utils.can_view_attendance",
                    },
                    {
                        "title": _("Leave Requests"),
                        "icon": "location_away",
                        "link": reverse_lazy("admin:leaves_leaverequest_changelist"),
                        "permission": "accounts.utils.can_view_leaves",
                    },
                    {
                        "title": _("My Payroll"),
                        "icon": "account_balance_wallet",
                        "link": reverse_lazy("payroll:my_summary"),
                        "permission": "accounts.utils.can_view_my_payroll",
                    },
                    {
                        "title": _("Open Console"),
                        "icon": "dashboard",
                        "link": "/console/",
                        "permission": "accounts.utils.can_view_pm_calculations",
                    },
                    {
                        "title": _("Notifications"),
                        "icon": "notifications",
                        "link": reverse_lazy("admin:accounts_notification_changelist"),
                        "badge": "accounts.utils.notifications_unread_badge",
                        "permission": "accounts.utils.can_view_notifications",
                    },
                ],
            },
        ],
}
}
