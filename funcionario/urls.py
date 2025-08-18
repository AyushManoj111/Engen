# urls.py
from django.contrib import admin
from django.urls import path, include
from funcionario import views

urlpatterns = [
    
    path('login/', views.login_funcionario_view, name='funcionariologin'),
    path('logout/', views.logout_view, name='funcionariologout'),
    path('dashboard/', views.scan_senha_view, name='funcionariodashboard'),
    path('scan-senha/', views.scan_senha_view, name='scan_senha'),
    
]