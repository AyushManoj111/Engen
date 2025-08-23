from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Sum, Count, Q
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction
from .models import Funcionario, Cliente, RequisicaoSenhas, Senha, RequisicaoSaldo
from empresas.models import Empresa
import logging
import csv
from django.http import HttpResponse
from openpyxl import Workbook
from django.contrib.auth.models import User, Group
from django.db import transaction

# Configurar logging
logger = logging.getLogger(__name__)

def is_gerente(user):
  """Verifica se o usuário é Gerente"""
  return user.groups.filter(name='Gerente').exists()

def get_empresa_usuario(user):
   """Retorna a empresa do usuário (gerente ou funcionário)"""
   try:
       if hasattr(user, 'empresa_gerenciada'):
           return user.empresa_gerenciada
       elif hasattr(user, 'funcionario'):
           return user.funcionario.empresa
   except:
       pass
   return None

def login_gerente_view(request):
   """View para login de gerente"""
   if request.method == 'POST':
       username = request.POST.get('username')
       password = request.POST.get('password')

       user = authenticate(request, username=username, password=password)

       if user is not None and user.groups.filter(name='Gerente').exists():
           login(request, user)
           return redirect('dashboard')
       else:
           messages.error(request, 'Apenas gerentes podem acessar este login.')
   
   return render(request, 'gerente/login.html')

@user_passes_test(is_gerente, login_url='/login/')
def dashboard_view(request):
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   total_funcionarios = Funcionario.objects.filter(empresa=empresa).count()
   total_clientes = Cliente.objects.filter(empresa=empresa).count()
   total_requisicoes = RequisicaoSenhas.objects.filter(empresa=empresa).count()

   requisicoes = RequisicaoSenhas.objects.filter(empresa=empresa).prefetch_related('lista_senhas')
   requisicoes_pendentes = sum(1 for r in requisicoes if r.senhas_restantes > 0)

   context = {
       'total_funcionarios': total_funcionarios,
       'total_clientes': total_clientes,
       'total_requisicoes': total_requisicoes,
       'requisicoes_pendentes': requisicoes_pendentes,
   }
   return render(request, 'gerente/dashboard.html', context)

def logout_view(request):
  """View para logout"""
  logout(request)
  messages.success(request, 'Você foi desconectado com sucesso')
  return redirect('')

def home_view(request):
  return render(request, 'gerente/home.html')

# ================================
# VIEWS DE FUNCIONÁRIOS
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def funcionarios(request):
   """Lista todos os funcionários"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   funcionarios = Funcionario.objects.filter(empresa=empresa, activo=True).order_by('-data_criacao')
   
   # Filtros opcionais
   search = request.GET.get('search', '')
   if search:
       funcionarios = funcionarios.filter(
           Q(user__first_name__icontains=search) | 
           Q(user__email__icontains=search) |
           Q(contacto__icontains=search)
       )
   
   context = {
       'funcionarios': funcionarios,
       'search': search,
   }
   return render(request, 'gerente/funcionarios.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def adicionar_funcionario(request):
   """Adicionar novo funcionário"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   if request.method == 'POST':
       try:
           nome = request.POST.get('nome', '').strip()
           email = request.POST.get('email', '').strip().lower()
           password = request.POST.get('password', '').strip()
           contacto = request.POST.get('contacto', '').strip()
           morada = request.POST.get('morada', '').strip()
           
           # Validações básicas
           if not nome or not email or not password:
               messages.error(request, 'Nome, email e password são obrigatórios.')
               return render(request, 'gerente/adicionar_funcionario.html')
           
           # Verificar se email já existe
           if User.objects.filter(email=email).exists():
               messages.error(request, 'Já existe um funcionário com este email.')
               return render(request, 'gerente/adicionar_funcionario.html')
           
           # Criar User e Funcionario numa transação
           with transaction.atomic():
               # Criar User
               user = User.objects.create_user(
                   username=email,  # Usar email como username
                   email=email,
                   first_name=nome,
                   password=password
               )
               
               # Adicionar ao grupo Funcionarios automaticamente
               funcionarios_group, created = Group.objects.get_or_create(name='Funcionarios')
               user.groups.add(funcionarios_group)
               
               # Criar Funcionário
               funcionario = Funcionario.objects.create(
                   user=user,
                   empresa=empresa,
                   contacto=contacto if contacto else None,
                   morada=morada if morada else None,
               )
           
           messages.success(request, f'Funcionário "{funcionario.nome}" adicionado com sucesso!')
           return redirect('funcionarios')
           
       except Exception as e:
           messages.error(request, f'Erro ao adicionar funcionário: {str(e)}')
   
   return render(request, 'gerente/adicionar_funcionario.html')

@user_passes_test(is_gerente, login_url='/login/')
def editar_funcionario(request, funcionario_id):
   """Editar funcionário existente"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   funcionario = get_object_or_404(Funcionario, id=funcionario_id, empresa=empresa, activo=True)
   
   if request.method == 'POST':
       try:
           nome = request.POST.get('nome', '').strip()
           email = request.POST.get('email', '').strip().lower()
           password = request.POST.get('password', '').strip()
           contacto = request.POST.get('contacto', '').strip()
           morada = request.POST.get('morada', '').strip()
           
           # Validações básicas
           if not nome or not email:
               messages.error(request, 'Nome e email são obrigatórios.')
               return render(request, 'gerente/editar_funcionario.html', {'funcionario': funcionario})
           
           # Verificar se email já existe (exceto o atual)
           if User.objects.filter(email=email).exclude(id=funcionario.user.id).exists():
               messages.error(request, 'Já existe outro funcionário com este email.')
               return render(request, 'gerente/editar_funcionario.html', {'funcionario': funcionario})
           
           # Atualizar User e Funcionario
           with transaction.atomic():
               # Atualizar User
               funcionario.user.first_name = nome
               funcionario.user.email = email
               funcionario.user.username = email
               if password:  # Só atualiza password se fornecida
                   funcionario.user.set_password(password)
               funcionario.user.save()
               
               # Atualizar Funcionário
               funcionario.contacto = contacto if contacto else None
               funcionario.morada = morada if morada else None
               funcionario.save()
           
           messages.success(request, f'Funcionário "{funcionario.nome}" atualizado com sucesso!')
           return redirect('funcionarios')
           
       except Exception as e:
           messages.error(request, f'Erro ao atualizar funcionário: {str(e)}')
   
   return render(request, 'gerente/editar_funcionario.html', {'funcionario': funcionario})

@user_passes_test(is_gerente, login_url='/login/')
def deletar_funcionario(request, funcionario_id):
   """Deletar funcionário (soft delete)"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   funcionario = get_object_or_404(Funcionario, id=funcionario_id, empresa=empresa, activo=True)
   
   try:
       funcionario.activo = False
       funcionario.save()
       messages.success(request, f'Funcionário "{funcionario.nome}" removido com sucesso!')
   except Exception as e:
       messages.error(request, f'Erro ao remover funcionário: {str(e)}')
   
   return redirect('funcionarios')

# ================================
# VIEWS DE CLIENTES
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def clientes(request):
   """Lista todos os clientes"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   clientes = Cliente.objects.filter(empresa=empresa).prefetch_related('requisicoes').order_by('-data_criacao')
   
   # Filtros opcionais
   search = request.GET.get('search', '')
   if search:
       clientes = clientes.filter(
           Q(nome__icontains=search) | 
           Q(email__icontains=search) |
           Q(contacto__icontains=search) |
           Q(endereco__icontains=search)
       )
   
   context = {
       'clientes': clientes,
       'search': search,
   }
   return render(request, 'gerente/clientes.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def adicionar_cliente(request):
   """Adicionar novo cliente"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   if request.method == 'POST':
       try:
           nome = request.POST.get('nome', '').strip()
           email = request.POST.get('email', '').strip()
           contacto = request.POST.get('contacto', '').strip()
           endereco = request.POST.get('endereco', '').strip()
           
           # Validações básicas
           if not nome:
               messages.error(request, 'Nome é obrigatório.')
               return render(request, 'gerente/adicionar_cliente.html')
           
           # Criar cliente
           cliente = Cliente.objects.create(
               empresa=empresa,
               nome=nome,
               email=email if email else None,
               contacto=contacto if contacto else None,
               endereco=endereco if endereco else None,
           )
           
           messages.success(request, f'Cliente "{cliente.nome}" adicionado com sucesso!')
           return redirect('clientes')
           
       except Exception as e:
           messages.error(request, f'Erro ao adicionar cliente: {str(e)}')
   
   return render(request, 'gerente/adicionar_cliente.html')

@user_passes_test(is_gerente, login_url='/login/')
def editar_cliente(request, cliente_id):
   """Editar cliente existente"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)
   
   if request.method == 'POST':
       try:
           nome = request.POST.get('nome', '').strip()
           email = request.POST.get('email', '').strip()
           contacto = request.POST.get('contacto', '').strip()
           endereco = request.POST.get('endereco', '').strip()
           
           # Validações básicas
           if not nome:
               messages.error(request, 'Nome é obrigatório.')
               return render(request, 'gerente/editar_cliente.html', {'cliente': cliente})
           
           # Atualizar cliente
           cliente.nome = nome
           cliente.email = email if email else None
           cliente.contacto = contacto if contacto else None
           cliente.endereco = endereco if endereco else None
           cliente.save()
           
           messages.success(request, f'Cliente "{cliente.nome}" atualizado com sucesso!')
           return redirect('clientes')
           
       except Exception as e:
           messages.error(request, f'Erro ao atualizar cliente: {str(e)}')
   
   return render(request, 'gerente/editar_cliente.html', {'cliente': cliente})

@user_passes_test(is_gerente, login_url='/login/')
def deletar_cliente(request, cliente_id):
   """Deletar cliente"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)
   
   try:
       # Verificar se cliente tem requisições ativas
       requisicoes_ativas = cliente.requisicoes.filter(ativa=True).count()
       if requisicoes_ativas > 0:
           messages.warning(request, f'Cliente "{cliente.nome}" possui {requisicoes_ativas} requisição(ões) ativa(s). Remova-as primeiro.')
           return redirect('clientes')
       
       cliente.delete()
       messages.success(request, f'Cliente "{cliente.nome}" removido com sucesso!')
   except Exception as e:
       messages.error(request, f'Erro ao remover cliente: {str(e)}')
   
   return redirect('clientes')

# ================================
# VIEWS DE REQUISIÇÕES SENHA
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def requisicoes(request):
   """Lista todas as requisições"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   requisicoes = (
       RequisicaoSenhas.objects.filter(empresa=empresa, ativa=True)
       .select_related('cliente')
       .prefetch_related('lista_senhas')
       .order_by('-data_criacao')
   )

   # Filtros opcionais
   status_filter = request.GET.get('status', '')
   search = request.GET.get('search', '')

   if search:
       requisicoes = requisicoes.filter(
           Q(cliente__nome__icontains=search) |
           Q(id__icontains=search)
       )

   # Filtragem por status (feito em Python, já que senhas_restantes é @property)
   if status_filter:
       if status_filter == 'completo':
           requisicoes = [r for r in requisicoes if r.senhas_restantes == 0]
       elif status_filter == 'baixo':
           requisicoes = [r for r in requisicoes if 0 < r.senhas_restantes <= 5]
       elif status_filter == 'medio':
           requisicoes = [r for r in requisicoes if 5 < r.senhas_restantes <= 15]
       elif status_filter == 'alto':
           requisicoes = [r for r in requisicoes if r.senhas_restantes > 15]

   # Estatísticas
   total_valor = sum(r.valor for r in requisicoes)
   total_senhas = sum(r.senhas for r in requisicoes)
   senhas_restantes_total = sum(r.senhas_restantes for r in requisicoes)

   context = {
       'requisicoes': requisicoes,
       'search': search,
       'status_filter': status_filter,
       'total_valor': total_valor,
       'total_senhas': total_senhas,
       'senhas_restantes_total': senhas_restantes_total,
   }
   return render(request, 'gerente/requisicoes.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def adicionar_requisicao(request):
   """Adicionar nova requisição"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')
   
   if request.method == 'POST':
       try:
           cliente_id = request.POST.get('cliente')
           valor = request.POST.get('valor')
           quantidade_senhas = request.POST.get('quantidade_senhas')
           
           if not cliente_id or not valor or not quantidade_senhas:
               messages.error(request, 'Cliente, valor e quantidade de senhas são obrigatórios.')
               return render(request, 'gerente/adicionar_requisicao.html', {'clientes': clientes})
           
           try:
               valor = float(valor)
               quantidade_senhas = int(quantidade_senhas)
           except ValueError:
               messages.error(request, 'Valor e quantidade devem ser números válidos.')
               return render(request, 'gerente/adicionar_requisicao.html', {'clientes': clientes})
           
           if valor <= 0 or quantidade_senhas <= 0:
               messages.error(request, 'Valor e quantidade devem ser maiores que zero.')
               return render(request, 'gerente/adicionar_requisicao.html', {'clientes': clientes})
           
           cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)

           # Usamos transaction.atomic para garantir consistência
           with transaction.atomic():
               requisicao = RequisicaoSenhas.objects.create(
                   empresa=empresa,
                   cliente=cliente,
                   valor=valor,
                   senhas=quantidade_senhas,
                   funcionario_responsavel=None
               )

               # Criar senhas random
               for _ in range(quantidade_senhas):
                   codigo = Senha.gerar_codigo()
                   # Garantir que não repete
                   while Senha.objects.filter(codigo=codigo).exists():
                       codigo = Senha.gerar_codigo()
                   Senha.objects.create(
                       empresa=empresa,
                       codigo=codigo,
                       requisicao=requisicao,
                       cliente=cliente
                   )
           
           messages.success(request, f'Requisição #{requisicao.id} criada com sucesso para {cliente.nome}!')
           return redirect('requisicoes')
           
       except Exception as e:
           messages.error(request, f'Erro ao criar requisição: {str(e)}')
   
   return render(request, 'gerente/adicionar_requisicao.html', {'clientes': clientes})

@user_passes_test(is_gerente, login_url='/login/')
def editar_requisicao(request, requisicao_id):
   """Editar requisição existente"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa, ativa=True)
   clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')
   
   if request.method == 'POST':
       try:
           cliente_id = request.POST.get('cliente')
           valor = request.POST.get('valor')
           quantidade_senhas = request.POST.get('quantidade_senhas')
           senhas_restantes = request.POST.get('senhas_restantes')
           
           if not cliente_id or not valor or not quantidade_senhas:
               messages.error(request, 'Cliente, valor e quantidade de senhas são obrigatórios.')
               return render(request, 'gerente/editar_requisicao.html', {
                   'requisicao': requisicao,
                   'clientes': clientes
               })
           
           try:
               valor = float(valor)
               quantidade_senhas = int(quantidade_senhas)
               senhas_restantes = int(senhas_restantes) if senhas_restantes else 0
           except ValueError:
               messages.error(request, 'Valores devem ser números válidos.')
               return render(request, 'gerente/editar_requisicao.html', {
                   'requisicao': requisicao,
                   'clientes': clientes
               })
           
           if valor <= 0 or quantidade_senhas <= 0:
               messages.error(request, 'Valor e quantidade devem ser maiores que zero.')
               return render(request, 'gerente/editar_requisicao.html', {
                   'requisicao': requisicao,
                   'clientes': clientes
               })
           
           if senhas_restantes > quantidade_senhas:
               messages.error(request, 'Senhas restantes não podem ser maiores que o total.')
               return render(request, 'gerente/editar_requisicao.html', {
                   'requisicao': requisicao,
                   'clientes': clientes
               })
           
           cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)

           with transaction.atomic():
               # Verificar se aumentou o total de senhas
               diferenca = quantidade_senhas - requisicao.senhas

               requisicao.cliente = cliente
               requisicao.valor = valor
               requisicao.senhas = quantidade_senhas
               requisicao.save()

               # Criar novas senhas se aumentou a quantidade
               if diferenca > 0:
                   for _ in range(diferenca):
                       codigo = Senha.gerar_codigo()
                       while Senha.objects.filter(codigo=codigo).exists():
                           codigo = Senha.gerar_codigo()
                       Senha.objects.create(
                           empresa=empresa,
                           codigo=codigo,
                           requisicao=requisicao,
                           cliente=cliente
                       )
           
           messages.success(request, f'Requisição #{requisicao.id} atualizada com sucesso!')
           return redirect('requisicoes')
           
       except Exception as e:
           messages.error(request, f'Erro ao atualizar requisição: {str(e)}')
   
   context = {
       'requisicao': requisicao,
       'clientes': clientes,
   }
   return render(request, 'gerente/editar_requisicao.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def deletar_requisicao(request, requisicao_id):
   """Deletar requisição (soft delete)"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa, ativa=True)
   
   try:
       requisicao.ativa = False
       requisicao.save()
       messages.success(request, f'Requisição #{requisicao.id} removida com sucesso!')
   except Exception as e:
       messages.error(request, f'Erro ao remover requisição: {str(e)}')
   
   return redirect('requisicoes')

@user_passes_test(is_gerente, login_url='/login/')
def ver_senhas(request, requisicao_id):
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa)
   senhas = requisicao.lista_senhas.all().order_by('data_criacao')
   return render(request, 'gerente/senhas.html', {
       'requisicao': requisicao,
       'senhas': senhas
   })

# ================================
# VIEWS DE REQUISIÇÕES SALDO
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def requisicoes_saldo(request):
  """Lista todas as requisições de saldo"""
  empresa = get_empresa_usuario(request.user)
  if not empresa:
      messages.error(request, 'Empresa não encontrada.')
      return redirect('login')
  
  requisicoes = (
      RequisicaoSaldo.objects.filter(empresa=empresa, ativa=True)
      .select_related('cliente')
      .prefetch_related('movimentos')
      .order_by('-data_criacao')
  )

  # Filtros opcionais
  status_filter = request.GET.get('status', '')
  search = request.GET.get('search', '')

  if search:
      requisicoes = requisicoes.filter(
          Q(cliente__nome__icontains=search) |
          Q(id__icontains=search) |
          Q(codigo__icontains=search)
      )

  # Filtragem por status (feito em Python, já que saldo_restante é @property)
  if status_filter:
      if status_filter == 'esgotado':
          requisicoes = [r for r in requisicoes if r.saldo_restante == 0]
      elif status_filter == 'baixo':
          requisicoes = [r for r in requisicoes if 0 < r.saldo_restante <= 50]
      elif status_filter == 'medio':
          requisicoes = [r for r in requisicoes if 50 < r.saldo_restante <= 200]
      elif status_filter == 'alto':
          requisicoes = [r for r in requisicoes if r.saldo_restante > 200]

  # Estatísticas
  total_valor = sum(r.valor_total for r in requisicoes)
  saldo_restante_total = sum(r.saldo_restante for r in requisicoes)

  context = {
      'requisicoes': requisicoes,
      'search': search,
      'status_filter': status_filter,
      'total_valor': total_valor,
      'saldo_restante_total': saldo_restante_total,
  }
  return render(request, 'gerente/requisicoes_saldo.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def adicionar_requisicao_saldo(request):
  """Adicionar nova requisição de saldo"""
  empresa = get_empresa_usuario(request.user)
  if not empresa:
      messages.error(request, 'Empresa não encontrada.')
      return redirect('login')
  
  clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')
  
  if request.method == 'POST':
      try:
          cliente_id = request.POST.get('cliente')
          valor_total = request.POST.get('valor_total')
          
          if not cliente_id or not valor_total:
              messages.error(request, 'Cliente e valor total são obrigatórios.')
              return render(request, 'gerente/adicionar_req_saldo.html', {'clientes': clientes})
          
          try:
              valor_total = float(valor_total)
          except ValueError:
              messages.error(request, 'Valor total deve ser um número válido.')
              return render(request, 'gerente/adicionar_req_saldo.html', {'clientes': clientes})
          
          if valor_total <= 0:
              messages.error(request, 'Valor total deve ser maior que zero.')
              return render(request, 'gerente/adicionar_req_saldo.html', {'clientes': clientes})
          
          cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)

          requisicao = RequisicaoSaldo.objects.create(
              empresa=empresa,
              cliente=cliente,
              valor_total=valor_total,
              funcionario_responsavel=None
          )
          
          messages.success(request, f'Requisição de saldo #{requisicao.id} ({requisicao.codigo}) criada com sucesso para {cliente.nome}!')
          return redirect('requisicoes_saldo')
          
      except Exception as e:
          messages.error(request, f'Erro ao criar requisição de saldo: {str(e)}')
  
  return render(request, 'gerente/adicionar_req_saldo.html', {'clientes': clientes})

@user_passes_test(is_gerente, login_url='/login/')
def editar_requisicao_saldo(request, requisicao_id):
  """Editar requisição de saldo existente"""
  empresa = get_empresa_usuario(request.user)
  if not empresa:
      messages.error(request, 'Empresa não encontrada.')
      return redirect('login')
  
  requisicao = get_object_or_404(RequisicaoSaldo, id=requisicao_id, empresa=empresa, ativa=True)
  clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')
  
  if request.method == 'POST':
      try:
          cliente_id = request.POST.get('cliente')
          valor_total = request.POST.get('valor_total')
          
          if not cliente_id or not valor_total:
              messages.error(request, 'Cliente e valor total são obrigatórios.')
              return render(request, 'gerente/editar_req_saldo.html', {
                  'requisicao': requisicao,
                  'clientes': clientes
              })
          
          try:
              valor_total = float(valor_total)
          except ValueError:
              messages.error(request, 'Valor total deve ser um número válido.')
              return render(request, 'gerente/editar_req_saldo.html', {
                  'requisicao': requisicao,
                  'clientes': clientes
              })
          
          if valor_total <= 0:
              messages.error(request, 'Valor total deve ser maior que zero.')
              return render(request, 'gerente/editar_req_saldo.html', {
                  'requisicao': requisicao,
                  'clientes': clientes
              })
          
          cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)

          requisicao.cliente = cliente
          requisicao.valor_total = valor_total
          requisicao.save()
          
          messages.success(request, f'Requisição de saldo #{requisicao.id} atualizada com sucesso!')
          return redirect('requisicoes_saldo')
          
      except Exception as e:
          messages.error(request, f'Erro ao atualizar requisição de saldo: {str(e)}')
  
  context = {
      'requisicao': requisicao,
      'clientes': clientes,
  }
  return render(request, 'gerente/editar_req_saldo.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def deletar_requisicao_saldo(request, requisicao_id):
  """Deletar requisição de saldo (soft delete)"""
  empresa = get_empresa_usuario(request.user)
  if not empresa:
      messages.error(request, 'Empresa não encontrada.')
      return redirect('login')
  
  requisicao = get_object_or_404(RequisicaoSaldo, id=requisicao_id, empresa=empresa, ativa=True)
  
  try:
      requisicao.ativa = False
      requisicao.save()
      messages.success(request, f'Requisição de saldo #{requisicao.id} removida com sucesso!')
  except Exception as e:
      messages.error(request, f'Erro ao remover requisição de saldo: {str(e)}')
  
  return redirect('requisicoes_saldo')

# ================================
# VIEWS ADICIONAIS
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def dashboard(request):
   """Dashboard principal com estatísticas"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   # Estatísticas gerais
   stats = {
       'total_funcionarios': Funcionario.objects.filter(empresa=empresa, activo=True).count(),
       'total_clientes': Cliente.objects.filter(empresa=empresa).count(),
       'total_requisicoes': RequisicaoSenhas.objects.filter(empresa=empresa, ativa=True).count(),
       'requisicoes_concluidas': RequisicaoSenhas.objects.filter(empresa=empresa, ativa=True, data_conclusao__isnull=False).count(),
   }
   
   # Requisições por status
   requisicoes_ativas = RequisicaoSenhas.objects.filter(empresa=empresa, ativa=True).prefetch_related('lista_senhas')
   
   requisicoes_status = {
       'alto': sum(1 for r in requisicoes_ativas if r.senhas_restantes > 15),
       'medio': sum(1 for r in requisicoes_ativas if 5 < r.senhas_restantes <= 15),
       'baixo': sum(1 for r in requisicoes_ativas if 0 < r.senhas_restantes <= 5),
       'completo': sum(1 for r in requisicoes_ativas if r.senhas_restantes == 0),
   }
   
   # Valores totais
   valores = RequisicaoSenhas.objects.filter(empresa=empresa, ativa=True).aggregate(
       valor_total=Sum('valor'),
       senhas_total=Sum('senhas')
   )
   
   senhas_restantes_total = sum(r.senhas_restantes for r in requisicoes_ativas)
   
   # Últimas requisições
   ultimas_requisicoes = RequisicaoSenhas.objects.filter(empresa=empresa, ativa=True).select_related('cliente').order_by('-data_criacao')[:5]
   
   # Clientes com mais requisições
   top_clientes = Cliente.objects.filter(empresa=empresa).annotate(
       num_requisicoes=Count('requisicoes', filter=Q(requisicoes__ativa=True))
   ).order_by('-num_requisicoes')[:5]
   
   context = {
       'stats': stats,
       'requisicoes_status': requisicoes_status,
       'valores': valores,
       'senhas_restantes_total': senhas_restantes_total,
       'ultimas_requisicoes': ultimas_requisicoes,
       'top_clientes': top_clientes,
   }
   return render(request, 'gerente/dashboard.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def requisicoes_cliente(request, cliente_id):
   """Lista todas as requisições de um cliente específico"""
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)
   requisicoes = cliente.requisicoes.filter(ativa=True).order_by('-data_criacao')
   
   # Paginação
   paginator = Paginator(requisicoes, 10)
   page_number = request.GET.get('page')
   page_obj = paginator.get_page(page_number)
   
   context = {
       'cliente': cliente,
       'requisicoes': page_obj,
   }
   return render(request, 'gerente/requisicoes_cliente.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def exportar_senhas_csv(request, requisicao_id):
   empresa = get_empresa_usuario(request.user)
   if not empresa:
       messages.error(request, 'Empresa não encontrada.')
       return redirect('login')
   
   requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa)
   senhas = requisicao.lista_senhas.all()

   response = HttpResponse(content_type='text/csv')
   response['Content-Disposition'] = f'attachment; filename="senhas_requisicao_{requisicao.id}.csv"'

   writer = csv.writer(response)
   writer.writerow(['Código', 'Cliente', 'Usada', 'Data Criação'])

   for senha in senhas:
       writer.writerow([
           senha.codigo,
           senha.cliente.nome,
           'Sim' if senha.usada else 'Não',
           senha.data_criacao.strftime("%d/%m/%Y %H:%M")
       ])

   return response

# ================================
# VIEWS AJAX (OPCIONAIS)
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def ajax_cliente_info(request, cliente_id):
   """Retorna informações do cliente em JSON"""
   try:
       empresa = get_empresa_usuario(request.user)
       if not empresa:
           return JsonResponse({'error': 'Empresa não encontrada'}, status=403)
       
       cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)
       # Calcular total de requisições
       total_requisicoes = cliente.requisicoes.filter(ativa=True).count()
       data = {
           'id': cliente.id,
           'nome': cliente.nome,
           'email': cliente.email,
           'contacto': cliente.contacto,
           'endereco': cliente.endereco,
           'total_requisicoes': total_requisicoes,
       }
       return JsonResponse(data)
   except:
       return JsonResponse({'error': 'Cliente não encontrado'}, status=404)