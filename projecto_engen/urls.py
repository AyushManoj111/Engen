# urls.py
from django.contrib import admin
from django.urls import path, include
from gerente import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('empresas/',include('empresas.urls')),
    path('gerente/',include('gerente.urls')),
    path('funcionario/',include('funcionario.urls')),
    path('',views.home_view,name=''),
    # AJAX
    path('ajax/cliente/<int:cliente_id>/', views.ajax_cliente_info, name='ajax_cliente_info'),
]