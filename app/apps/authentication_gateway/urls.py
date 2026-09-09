"""Session authentication routes used by the calculator."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import CalculatorLoginView

urlpatterns = [
    path("login/", CalculatorLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
]
