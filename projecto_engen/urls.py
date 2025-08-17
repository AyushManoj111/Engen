# urls.py
from django.urls import path
from gerente import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.dashboard_view, name='dashboard'),  # ou redirecionar para dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),

    path('funcionarios/', views.funcionarios, name='funcionarios'),
    path('funcionarios/adicionar/', views.adicionar_funcionario, name='adicionar_funcionario'),
    path('funcionarios/editar/<int:funcionario_id>/', views.editar_funcionario, name='editar_funcionario'),
    path('funcionarios/deletar/<int:funcionario_id>/', views.deletar_funcionario, name='deletar_funcionario'),
    
    path('clientes/', views.clientes, name='clientes'),
    path('clientes/adicionar/', views.adicionar_cliente, name='adicionar_cliente'),
    path('clientes/editar/<int:cliente_id>/', views.editar_cliente, name='editar_cliente'),
    path('clientes/deletar/<int:cliente_id>/', views.deletar_cliente, name='deletar_cliente'),
    path('clientes/<int:cliente_id>/requisicoes/', views.requisicoes_cliente, name='requisicoes_cliente'),
    
    path('requisicoes/', views.requisicoes, name='requisicoes'),
    path('requisicoes/adicionar/', views.adicionar_requisicao, name='adicionar_requisicao'),
    path('requisicoes/editar/<int:requisicao_id>/', views.editar_requisicao, name='editar_requisicao'),
    path('requisicoes/deletar/<int:requisicao_id>/', views.deletar_requisicao, name='deletar_requisicao'),
    path('requisicoes/<int:requisicao_id>/senhas/', views.ver_senhas, name='ver_senhas'),
    path('requisicoes/<int:requisicao_id>/exportar/csv/', views.exportar_senhas_csv, name='exportar_senhas_csv'),
    
    # AJAX
    path('ajax/cliente/<int:cliente_id>/', views.ajax_cliente_info, name='ajax_cliente_info'),
]