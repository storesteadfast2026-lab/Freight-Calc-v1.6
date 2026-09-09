from django.urls import path

from . import views

app_name = 'saved_estimates'

urlpatterns = [
    path('', views.estimate_list, name='list'),
    path('<str:reference>/print/', views.estimate_print, name='print'),
    path('<str:reference>/export.csv', views.estimate_csv, name='csv'),
    path('<str:reference>/export.xlsx', views.estimate_xlsx, name='xlsx'),
]

