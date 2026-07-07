from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path('admin/', admin.site.urls),
    path('console/', include('console.urls')),
    path('', include('accounts.urls')),
    path("attendance/", include("attendance.urls")),
    path("payroll/", include("payroll.urls")),
    path("leaves/", include("leaves.urls")),


]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
