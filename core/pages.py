"""Server-rendered pages: the login screen and the single-page app shell."""
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

DEMO_ACCOUNTS = {
    "manager": "lakshmi",
    "member": "fatima",
    "student": "nikhil",
}


def login_view(request):
    if request.user.is_authenticated:
        return redirect("app")
    error = None
    if request.method == "POST":
        user = authenticate(request, username=request.POST.get("username", ""), password=request.POST.get("password", ""))
        if user:
            login(request, user)
            return redirect(request.GET.get("next") or "app")
        error = "That username and password don't match."
    return render(request, "login.html", {"error": error, "demo": settings.DEMO_MODE})


@require_POST
def demo_login(request, role):
    if not settings.DEMO_MODE or role not in DEMO_ACCOUNTS:
        raise Http404
    user = User.objects.filter(username=DEMO_ACCOUNTS[role]).first()
    if user is None:
        return render(request, "login.html", {"error": "Demo data not loaded. Run: python manage.py seed_demo", "demo": True})
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("app")


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def app_shell(request):
    return render(request, "app.html")
