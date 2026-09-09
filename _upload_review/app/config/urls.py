from django.contrib import admin
from django.urls import path
from apps.freight import views as freight_views

admin.site.site_header = "Steadfast Freight Calculator Administration"
admin.site.site_title = "Steadfast Freight Calculator Administration"
admin.site.index_title = "Steadfast Fright Calculator Administration"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', freight_views.calculator_page, name='freight_calculator'),
    path('api/suburbs/', freight_views.suburb_autocomplete, name='suburb_autocomplete'),
    path('api/products/', freight_views.product_autocomplete, name='product_autocomplete'),
    path('api/calculate/', freight_views.calculate_freight, name='calculate_freight'),
]
