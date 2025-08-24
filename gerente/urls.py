from django.contrib import admin
from django.urls import path, include
from gerente import views
from django.contrib.auth.views import LoginView, LogoutView

urlpatterns = [

    path('login', views.login_gerente_view, name='login'),
    path('logout', views.logout_view, name='logout'),
    path('dashboard', views.dashboard_view, name='dashboard'),

    path('funcionarios/', views.funcionarios, name='funcionarios'),
    path('funcionarios/adicionar/', views.adicionar_funcionario, name='adicionar_funcionario'),
    path('funcionarios/editar/<int:funcionario_id>/', views.editar_funcionario, name='editar_funcionario'),
    path('funcionarios/deletar/<int:funcionario_id>/', views.deletar_funcionario, name='deletar_funcionario'),
    
    path('clientes/', views.clientes, name='clientes'),
    path('clientes/adicionar/', views.adicionar_cliente, name='adicionar_cliente'),
    path('clientes/editar/<int:cliente_id>/', views.editar_cliente, name='editar_cliente'),
    path('clientes/deletar/<int:cliente_id>/', views.deletar_cliente, name='deletar_cliente'),
    path('clientes/<int:cliente_id>/requisicoes/', views.requisicoes_cliente, name='requisicoes_cliente'),
    path("clientes/<int:cliente_id>/extrato/", views.extrato_cliente, name="extrato_cliente"),
    
    path('requisicoes/', views.requisicoes, name='requisicoes'),
    path('requisicoes/adicionar/', views.adicionar_requisicao, name='adicionar_requisicao'),
    path('requisicoes/editar/<int:requisicao_id>/', views.editar_requisicao, name='editar_requisicao'),
    path('requisicoes/deletar/<int:requisicao_id>/', views.deletar_requisicao, name='deletar_requisicao'),
    path('requisicoes/<int:requisicao_id>/senhas/', views.ver_senhas, name='ver_senhas'),
    path('requisicoes/<int:requisicao_id>/exportar/csv/', views.exportar_senhas_csv, name='exportar_senhas_csv'),
    
    path('requisicoes-saldo/', views.requisicoes_saldo, name='requisicoes_saldo'),
    path('requisicoes-saldo/adicionar/', views.adicionar_requisicao_saldo, name='adicionar_requisicao_saldo'),
    path('requisicoes-saldo/adicionar/<int:cliente_id>/', views.adicionar_requisicao_saldo, name='adicionar_req_saldo'),
    path('requisicoes-saldo/<int:requisicao_id>/editar/', views.editar_requisicao_saldo, name='editar_requisicao_saldo'),
    path('requisicoes-saldo/<int:requisicao_id>/deletar/', views.deletar_requisicao_saldo, name='deletar_requisicao_saldo'),

    path('requisicao/<int:requisicao_id>/recibo-pdf/', views.gerar_recibo_pdf, name='gerar_recibo_pdf'),
    path('requisicao-saldo/<int:requisicao_id>/recibo-pdf/', views.gerar_recibo_saldo_pdf, name='gerar_recibo_saldo_pdf'),
]