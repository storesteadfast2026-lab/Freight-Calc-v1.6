from django.urls import path

from . import views

app_name = 'saved_estimates_api'

urlpatterns = [
    path('save/', views.estimate_save_api, name='save'),
    path('<str:reference>/duplicate/', views.estimate_duplicate_api, name='duplicate'),
]

