from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.freight import views as freight_views

admin.site.site_header = 'Steadfast Freight Calculator Administration'
admin.site.site_title = 'Steadfast Freight Calculator Administration'
admin.site.index_title = 'Steadfast Freight Calculator Administration'

urlpatterns = [
    path("accounts/", include("apps.authentication_gateway.urls")),
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(template_name='registration/login.html'),
        name='login',
    ),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('', freight_views.calculator_page, name='freight_calculator'),
    path('api/suburbs/', freight_views.suburb_autocomplete, name='suburb_autocomplete'),
    path('api/products/', freight_views.product_autocomplete, name='product_autocomplete'),
    path('api/calculate/', freight_views.calculate_freight, name='calculate_freight'),
]

handler403 = "apps.authentication_gateway.views.permission_denied_view"

