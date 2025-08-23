from django.urls import path
from . import views

urlpatterns = [
    path('criar/', views.criar_empresa, name='criar_empresa'),
]