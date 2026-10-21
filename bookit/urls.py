from django.contrib import admin
from django.urls import include, path

from core import pages

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    path("login/", pages.login_view, name="login"),
    path("logout/", pages.logout_view, name="logout"),
    path("demo-login/<str:role>/", pages.demo_login, name="demo-login"),
    path("", pages.app_shell, name="app"),
]
