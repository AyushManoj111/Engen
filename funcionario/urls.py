# urls.py
from django.contrib import admin
from django.urls import path, include
from funcionario import views

urlpatterns = [
    
    path('login/', views.login_funcionario_view, name='funcionariologin'),
    path('logout/', views.logout_view, name='funcionariologout'),
    path('dashboard/', views.scan_senha_view, name='funcionariodashboard'),
    path('scan-senha/', views.scan_senha_view, name='scan_senha'),
    path('camera-stream/', views.camera_stream, name='camera_stream'),
    path('stop-camera/', views.stop_camera, name='stop_camera'),
    path('scan-qr-code/', views.scan_qr_code, name='scan_qr_code'),
    path('process-scanned-code/', views.process_scanned_code, name='process_scanned_code'),
]