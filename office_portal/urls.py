from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView


urlpatterns = [
    # Django admin is fully blocked — the console handles everything.
    # The admin URLconf stays mounted below only so legacy reverse('admin:...')
    # calls keep resolving; this catch-all intercepts every request first.
    re_path(r'^admin/', RedirectView.as_view(url='/console/', permanent=False)),
    path('admin/', admin.site.urls),
    path('console/', include('console.urls')),
    path('', include('accounts.urls')),
    path("attendance/", include("attendance.urls")),
    path("payroll/", include("payroll.urls")),
    path("leaves/", include("leaves.urls")),
    path("projects/", include("projects.urls")),


]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
