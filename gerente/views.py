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
from datetime import datetime
import io
from django.template.loader import get_template
from xhtml2pdf import pisa
from decimal import Decimal, InvalidOperation

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.colors import black, blue
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

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
            forma_pagamento = request.POST.get('forma_pagamento')
            banco = request.POST.get('banco', '')  # NOVO CAMPO
            observacoes = request.POST.get('observacoes', '')
            
            # Validações básicas
            if not cliente_id or not valor or not quantidade_senhas or not forma_pagamento:
                messages.error(request, 'Todos os campos obrigatórios devem ser preenchidos.')
                return render(request, 'gerente/adicionar_requisicao.html', {'clientes': clientes})
            
            # Validar banco obrigatório para transferência
            if forma_pagamento == 'transferencia' and not banco.strip():
                messages.error(request, 'Nome do banco é obrigatório para transferência bancária.')
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
            
            # Validar forma de pagamento
            formas_validas = ['transferencia', 'cash', 'pos']
            if forma_pagamento not in formas_validas:
                messages.error(request, 'Forma de pagamento inválida.')
                return render(request, 'gerente/adicionar_requisicao.html', {'clientes': clientes})
            
            cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)

            # Usamos transaction.atomic para garantir consistência
            with transaction.atomic():
                requisicao = RequisicaoSenhas.objects.create(
                    empresa=empresa,
                    cliente=cliente,
                    valor=valor,
                    senhas=quantidade_senhas,
                    forma_pagamento=forma_pagamento,
                    banco=banco if forma_pagamento == 'transferencia' else None,  # NOVO CAMPO
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
            
            messages.success(request, f'Requisição #{requisicao.id} criada com sucesso!')
            
            # Renderizar template com modal de recibo
            return render(request, 'gerente/adicionar_requisicao.html', {
                'clientes': clientes,
                'mostrar_recibo': True,
                'requisicao': requisicao
            })
            
        except Exception as e:
            messages.error(request, f'Erro ao criar requisição: {str(e)}')
    
    return render(request, 'gerente/adicionar_requisicao.html', {
        'clientes': clientes,
        'mostrar_recibo': False
    })

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
           forma_pagamento = request.POST.get('forma_pagamento')  # NOVO CAMPO
           banco = request.POST.get('banco', '')  # NOVO CAMPO
           
           if not cliente_id or not valor or not quantidade_senhas or not forma_pagamento:
               messages.error(request, 'Cliente, valor, quantidade de senhas e forma de pagamento são obrigatórios.')
               return render(request, 'gerente/editar_requisicao.html', {
                   'requisicao': requisicao,
                   'clientes': clientes
               })
           
           # Validar banco obrigatório para transferência
           if forma_pagamento == 'transferencia' and not banco.strip():
               messages.error(request, 'Nome do banco é obrigatório para transferência bancária.')
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
           
           # Validar forma de pagamento
           formas_validas = ['transferencia', 'cash', 'pos']
           if forma_pagamento not in formas_validas:
               messages.error(request, 'Forma de pagamento inválida.')
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
               requisicao.forma_pagamento = forma_pagamento  # NOVO CAMPO
               requisicao.banco = banco if forma_pagamento == 'transferencia' else None  # NOVO CAMPO
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
    """View para adicionar nova requisição de saldo"""
    if request.method == 'POST':
        try:
            empresa = get_empresa_usuario(request.user)
            if not empresa:
                messages.error(request, 'Empresa não encontrada.')
                return redirect('login')
            
            # Obter dados do formulário com validação
            cliente_id = request.POST.get('cliente')
            valor_total_str = request.POST.get('valor_total', '0')
            forma_pagamento = request.POST.get('forma_pagamento')
            banco = request.POST.get('banco', '').strip()
            
            # Validar campos obrigatórios
            if not cliente_id:
                messages.error(request, 'Cliente é obrigatório.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa)
                })
            
            if not forma_pagamento:
                messages.error(request, 'Forma de pagamento é obrigatória.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa)
                })
            
            # CORREÇÃO PRINCIPAL: Converter valor para Decimal/float corretamente
            try:
                # Limpar string e converter para Decimal
                valor_total_str = valor_total_str.replace(',', '.').strip()
                valor_total = Decimal(valor_total_str)
                
                # Validar se o valor é positivo
                if valor_total <= 0:
                    messages.error(request, 'Valor total deve ser maior que zero.')
                    return render(request, 'gerente/adicionar_req_saldo.html', {
                        'clientes': Cliente.objects.filter(empresa=empresa)
                    })
                    
            except (ValueError, InvalidOperation, TypeError) as e:
                messages.error(request, f'Valor total inválido: {valor_total_str}. Use apenas números.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa)
                })
            
            # Obter cliente
            try:
                cliente = Cliente.objects.get(id=int(cliente_id), empresa=empresa)
            except (Cliente.DoesNotExist, ValueError):
                messages.error(request, 'Cliente não encontrado.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa)
                })
            
            # Validar banco para transferência
            if forma_pagamento == 'transferencia' and not banco:
                messages.error(request, 'Nome do banco é obrigatório para transferência bancária.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa)
                })
            
            # Criar a requisição de saldo
            requisicao = RequisicaoSaldo.objects.create(
                empresa=empresa,
                cliente=cliente,
                valor_total=valor_total,
                forma_pagamento=forma_pagamento,
                banco=banco if forma_pagamento == 'transferencia' else None,
                ativa=True
            )
            
            # Log da transação
            print(f"Requisição de saldo criada: ID={requisicao.id}, Valor={valor_total}, Cliente={cliente.nome}")
            
            messages.success(request, f'Requisição de saldo criada com sucesso! Código: {requisicao.codigo}')
            
            # Renderizar template com o recibo
            return render(request, 'gerente/adicionar_req_saldo.html', {
                'clientes': Cliente.objects.filter(empresa=empresa),
                'mostrar_recibo': True,
                'requisicao': requisicao
            })
            
        except Exception as e:
            # Log detalhado do erro
            print(f"Erro ao criar requisição de saldo: {str(e)}")
            print(f"Tipo do erro: {type(e)}")
            import traceback
            traceback.print_exc()
            
            messages.error(request, f'Erro ao criar requisição de saldo: {str(e)}')
            return render(request, 'gerente/adicionar_req_saldo.html', {
                'clientes': Cliente.objects.filter(empresa=empresa)
            })
    
    else:
        # GET request - mostrar formulário
        empresa = get_empresa_usuario(request.user)
        if not empresa:
            messages.error(request, 'Empresa não encontrada.')
            return redirect('login')
            
        clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')
        
        return render(request, 'gerente/adicionar_req_saldo.html', {
            'clientes': clientes
        })


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
          forma_pagamento = request.POST.get('forma_pagamento')  # NOVO CAMPO
          banco = request.POST.get('banco', '')  # NOVO CAMPO
          
          if not cliente_id or not valor_total or not forma_pagamento:
              messages.error(request, 'Cliente, valor total e forma de pagamento são obrigatórios.')
              return render(request, 'gerente/editar_req_saldo.html', {
                  'requisicao': requisicao,
                  'clientes': clientes
              })
          
          # Validar banco obrigatório para transferência
          if forma_pagamento == 'transferencia' and not banco.strip():
              messages.error(request, 'Nome do banco é obrigatório para transferência bancária.')
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
          
          # Validar forma de pagamento
          formas_validas = ['transferencia', 'cash', 'pos']
          if forma_pagamento not in formas_validas:
              messages.error(request, 'Forma de pagamento inválida.')
              return render(request, 'gerente/editar_req_saldo.html', {
                  'requisicao': requisicao,
                  'clientes': clientes
              })
          
          cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)

          requisicao.cliente = cliente
          requisicao.valor_total = valor_total
          requisicao.forma_pagamento = forma_pagamento  # NOVO CAMPO
          requisicao.banco = banco if forma_pagamento == 'transferencia' else None  # NOVO CAMPO
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

@user_passes_test(is_gerente, login_url='/login/')
def gerar_recibo_pdf(request, requisicao_id):
    """View para gerar PDF do recibo usando xhtml2pdf"""
    try:
        empresa = get_empresa_usuario(request.user)
        if not empresa:
            messages.error(request, 'Empresa não encontrada.')
            return redirect('login')
        
        requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa)
        
        # Template HTML para PDF
        template_string = '''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Recibo - Requisição #{}</title>
            <style>
                @page {{
                    size: A4;
                    margin: 2cm;
                }}
                body {{
                    font-family: Arial, sans-serif;
                    font-size: 12px;
                    line-height: 1.4;
                    color: #333;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 20px;
                }}
                .empresa-nome {{
                    font-size: 28px;
                    font-weight: bold;
                    color: #2c3e50;
                    margin-bottom: 8px;
                }}
                .empresa-desc {{
                    color: #666;
                    font-size: 14px;
                    font-style: italic;
                }}
                .recibo-info {{
                    display: flex;
                    justify-content: space-between;
                    margin-bottom: 25px;
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 8px;
                    border-left: 4px solid #3498db;
                }}
                .recibo-numero {{
                    text-align: right;
                }}
                .details-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 25px 0;
                    background: white;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .details-table td {{
                    padding: 15px;
                    border-bottom: 1px solid #e9ecef;
                }}
                .details-table tr:nth-child(even) {{
                    background-color: #f8f9fa;
                }}
                .details-table .label {{
                    font-weight: bold;
                    width: 220px;
                    color: #2c3e50;
                    border-right: 2px solid #e9ecef;
                }}
                .details-table .value {{
                    color: #495057;
                    font-weight: 500;
                }}
                .valor-destaque {{
                    font-size: 16px;
                    font-weight: bold;
                    color: #3498db;
                }}
                .senhas-destaque {{
                    font-size: 14px;
                    font-weight: bold;
                    color: #e67e22;
                }}
                .status-ativa {{
                    color: #27ae60;
                    font-weight: bold;
                    text-transform: uppercase;
                }}
                .status-inativa {{
                    color: #e74c3c;
                    font-weight: bold;
                    text-transform: uppercase;
                }}
                .info-box {{
                    background: #e3f2fd;
                    border: 1px solid #bbdefb;
                    border-radius: 8px;
                    padding: 20px;
                    margin: 25px 0;
                    border-left: 4px solid #2196f3;
                }}
                .info-box h4 {{
                    margin: 0 0 15px 0;
                    color: #0d47a1;
                    font-size: 14px;
                    font-weight: bold;
                }}
                .info-box ul {{
                    margin: 0;
                    padding-left: 20px;
                    color: #495057;
                    font-size: 11px;
                }}
                .info-box li {{
                    margin-bottom: 8px;
                    line-height: 1.3;
                }}
                .divider {{
                    height: 2px;
                    background: linear-gradient(to right, #3498db, #2c3e50);
                    margin: 25px 0;
                    border-radius: 1px;
                }}
                .signature {{
                    margin-top: 50px;
                    text-align: center;
                }}
                .signature-line {{
                    border-top: 2px solid #333;
                    width: 350px;
                    margin: 40px auto 10px auto;
                }}
                .signature-text {{
                    color: #666;
                    font-size: 12px;
                    font-weight: bold;
                }}
                .footer {{
                    margin-top: 40px;
                    text-align: center;
                    padding-top: 20px;
                    border-top: 1px solid #e9ecef;
                }}
                .footer small {{
                    color: #6c757d;
                    font-size: 10px;
                }}
                .watermark {{
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%) rotate(-45deg);
                    font-size: 80px;
                    color: rgba(52, 152, 219, 0.05);
                    font-weight: bold;
                    z-index: -1;
                }}
            </style>
        </head>
        <body>
            <div class="watermark">SENHAS</div>
            
            <div class="header">
                <div class="empresa-nome">{}</div>
                <div class="empresa-desc">Sistema de Gestão de Requisições</div>
            </div>
            
            <div class="recibo-info">
                <div>
                    <strong>Recibo Nº:</strong> {:06d}<br>
                    <strong>Código:</strong> RS-{:06d}<br>
                    <strong>Tipo:</strong> Requisição de Senhas
                </div>
                <div class="recibo-numero">
                    <strong>Data de Criação:</strong> {}<br>
                    <strong>Impresso em:</strong> {}
                </div>
            </div>
            
            <div class="divider"></div>
            
            <table class="details-table">
                <tr>
                    <td class="label">Cliente:</td>
                    <td class="value">{}</td>
                </tr>
                <tr>
                    <td class="label">Valor:</td>
                    <td class="value valor-destaque">{:.2f} MT</td>
                </tr>
                <tr>
                    <td class="label">Quantidade de Senhas:</td>
                    <td class="value senhas-destaque">{}</td>
                </tr>
                <tr>
                    <td class="label">Forma de Pagamento:</td>
                    <td class="value">{}</td>
                </tr>
                <tr>
                    <td class="label">Status:</td>
                    <td class="value {}">{}</td>
                </tr>
                <tr>
                    <td class="label">Senhas Restantes:</td>
                    <td class="value senhas-destaque">{}</td>
                </tr>
                <tr>
                    <td class="label">Data de Criação:</td>
                    <td class="value">{}</td>
                </tr>
            </table>
            
            <div class="info-box">
                <h4>ℹ️ INFORMAÇÕES IMPORTANTES</h4>
                <ul>
                    <li>Estas senhas poderão ser utilizadas para movimentações na plataforma</li>
                    <li>O número de senhas restantes será atualizado automaticamente a cada utilização</li>
                    <li>Guarde este recibo como comprovante oficial de pagamento e aquisição de senhas</li>
                    <li>Para consultas sobre o uso das senhas, acesse o histórico no sistema</li>
                    <li>Em caso de dúvidas ou problemas, entre em contato com o suporte técnico</li>
                    <li>Este documento tem validade legal como comprovante de transação</li>
                </ul>
            </div>
            
            <div class="signature">
                <div class="signature-line"></div>
                <p class="signature-text">Assinatura do Responsável</p>
            </div>
            
            <div class="footer">
                <small>
                    Este documento foi gerado automaticamente pelo sistema em {} | 
                    Recibo Nº {:06d} | 
                    Código: RS-{:06d} | 
                    Processado por: {}
                </small>
            </div>
        </body>
        </html>
        '''.format(
            requisicao.id,
            empresa.nome,
            requisicao.id,
            requisicao.id,
            requisicao.data_criacao.strftime('%d/%m/%Y às %H:%M'),
            datetime.now().strftime('%d/%m/%Y às %H:%M:%S'),
            requisicao.cliente.nome,
            float(requisicao.valor),
            requisicao.senhas,
            requisicao.get_forma_pagamento_display(),
            'status-ativa' if requisicao.ativa else 'status-inativa',
            'ATIVA' if requisicao.ativa else 'INATIVA',
            requisicao.senhas_restantes,
            requisicao.data_criacao.strftime('%d/%m/%Y às %H:%M:%S'),
            datetime.now().strftime('%d/%m/%Y às %H:%M:%S'),
            requisicao.id,
            requisicao.id,
            request.user.get_full_name() or request.user.username
        )
        
        # Gerar PDF
        result = io.BytesIO()
        pdf = pisa.pisaDocument(io.BytesIO(template_string.encode("UTF-8")), result)
        
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            filename = f'recibo_requisicao_{requisicao.id:06d}_{requisicao.data_criacao.strftime("%Y%m%d")}.pdf'
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        else:
            messages.error(request, 'Erro ao gerar PDF.')
            return redirect('requisicoes')
            
    except Exception as e:
        messages.error(request, f'Erro ao gerar PDF: {str(e)}')
        return redirect('requisicoes')

@user_passes_test(is_gerente, login_url='/login/')
def gerar_recibo_saldo_pdf(request, requisicao_id):
    """View para gerar PDF do recibo de requisição de saldo usando xhtml2pdf"""
    try:
        empresa = get_empresa_usuario(request.user)
        if not empresa:
            messages.error(request, 'Empresa não encontrada.')
            return redirect('login')
        
        # Assumindo que você tem um modelo RequisicaoSaldo
        # Se for o mesmo modelo, ajuste o nome conforme necessário
        requisicao = get_object_or_404(RequisicaoSaldo, id=requisicao_id, empresa=empresa)
        
        # Template HTML para PDF do recibo de saldo
        template_string = '''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Recibo de Saldo - Requisição #{}</title>
            <style>
                @page {{
                    size: A4;
                    margin: 2cm;
                }}
                body {{
                    font-family: Arial, sans-serif;
                    font-size: 12px;
                    line-height: 1.4;
                    color: #333;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                    border-bottom: 3px solid #27ae60;
                    padding-bottom: 20px;
                }}
                .empresa-nome {{
                    font-size: 28px;
                    font-weight: bold;
                    color: #2c3e50;
                    margin-bottom: 8px;
                }}
                .empresa-desc {{
                    color: #666;
                    font-size: 14px;
                    font-style: italic;
                }}
                .recibo-info {{
                    display: flex;
                    justify-content: space-between;
                    margin-bottom: 25px;
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 8px;
                    border-left: 4px solid #27ae60;
                }}
                .recibo-numero {{
                    text-align: right;
                }}
                .details-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 25px 0;
                    background: white;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .details-table td {{
                    padding: 15px;
                    border-bottom: 1px solid #e9ecef;
                }}
                .details-table tr:nth-child(even) {{
                    background-color: #f8f9fa;
                }}
                .details-table .label {{
                    font-weight: bold;
                    width: 220px;
                    color: #2c3e50;
                    border-right: 2px solid #e9ecef;
                }}
                .details-table .value {{
                    color: #495057;
                    font-weight: 500;
                }}
                .valor-destaque {{
                    font-size: 16px;
                    font-weight: bold;
                    color: #27ae60;
                }}
                .valor-saldo {{
                    font-size: 14px;
                    font-weight: bold;
                    color: #3498db;
                }}
                .status-ativa {{
                    color: #27ae60;
                    font-weight: bold;
                    text-transform: uppercase;
                }}
                .status-inativa {{
                    color: #e74c3c;
                    font-weight: bold;
                    text-transform: uppercase;
                }}
                .info-box {{
                    background: #e8f4fd;
                    border: 1px solid #bee5eb;
                    border-radius: 8px;
                    padding: 20px;
                    margin: 25px 0;
                    border-left: 4px solid #17a2b8;
                }}
                .info-box h4 {{
                    margin: 0 0 15px 0;
                    color: #0c5460;
                    font-size: 14px;
                    font-weight: bold;
                }}
                .info-box ul {{
                    margin: 0;
                    padding-left: 20px;
                    color: #495057;
                    font-size: 11px;
                }}
                .info-box li {{
                    margin-bottom: 8px;
                    line-height: 1.3;
                }}
                .divider {{
                    height: 2px;
                    background: linear-gradient(to right, #27ae60, #2c3e50);
                    margin: 25px 0;
                    border-radius: 1px;
                }}
                .signature {{
                    margin-top: 50px;
                    text-align: center;
                }}
                .signature-line {{
                    border-top: 2px solid #333;
                    width: 350px;
                    margin: 40px auto 10px auto;
                }}
                .signature-text {{
                    color: #666;
                    font-size: 12px;
                    font-weight: bold;
                }}
                .footer {{
                    margin-top: 40px;
                    text-align: center;
                    padding-top: 20px;
                    border-top: 1px solid #e9ecef;
                }}
                .footer small {{
                    color: #6c757d;
                    font-size: 10px;
                }}
                .watermark {{
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%) rotate(-45deg);
                    font-size: 80px;
                    color: rgba(39, 174, 96, 0.05);
                    font-weight: bold;
                    z-index: -1;
                }}
            </style>
        </head>
        <body>
            <div class="watermark">SALDO</div>
            
            <div class="header">
                <div class="empresa-nome">{}</div>
                <div class="empresa-desc">Sistema de Gestão de Requisições de Saldo</div>
            </div>
            
            <div class="recibo-info">
                <div>
                    <strong>Recibo Nº:</strong> {:06d}<br>
                    <strong>Código:</strong> {}<br>
                    <strong>Tipo:</strong> Requisição de Saldo
                </div>
                <div class="recibo-numero">
                    <strong>Data de Criação:</strong> {}<br>
                    <strong>Impresso em:</strong> {}
                </div>
            </div>
            
            <div class="divider"></div>
            
            <table class="details-table">
                <tr>
                    <td class="label">Cliente:</td>
                    <td class="value">{}</td>
                </tr>
                <tr>
                    <td class="label">Valor Total:</td>
                    <td class="value valor-destaque">{:.2f} MT</td>
                </tr>
                <tr>
                    <td class="label">Saldo Restante:</td>
                    <td class="value valor-saldo">{:.2f} MT</td>
                </tr>
                <tr>
                    <td class="label">Forma de Pagamento:</td>
                    <td class="value">{}</td>
                </tr>
                {}
                <tr>
                    <td class="label">Status:</td>
                    <td class="value {}">{}</td>
                </tr>
                <tr>
                    <td class="label">Data de Criação:</td>
                    <td class="value">{}</td>
                </tr>
            </table>
            
            <div class="info-box">
                <h4>ℹ️ INFORMAÇÕES IMPORTANTES</h4>
                <ul>
                    <li>Este saldo poderá ser utilizado para movimentações futuras na plataforma</li>
                    <li>O saldo restante será atualizado automaticamente a cada movimentação realizada</li>
                    <li>Guarde este recibo como comprovante oficial de pagamento e crédito de saldo</li>
                    <li>Para consultas sobre movimentações, acesse o histórico no sistema</li>
                    <li>Em caso de dúvidas ou problemas, entre em contato com o suporte técnico</li>
                    <li>Este documento tem validade legal como comprovante de transação</li>
                </ul>
            </div>
            
            <div class="signature">
                <div class="signature-line"></div>
                <p class="signature-text">Assinatura do Responsável</p>
            </div>
            
            <div class="footer">
                <small>
                    Este documento foi gerado automaticamente pelo sistema em {} | 
                    Recibo Nº {:06d} | 
                    Código: {} | 
                    Processado por: {}
                </small>
            </div>
        </body>
        </html>
        '''.format(
            requisicao.id,
            empresa.nome,
            requisicao.id,
            getattr(requisicao, 'codigo', f'RS-{requisicao.id:06d}'),
            requisicao.data_criacao.strftime('%d/%m/%Y às %H:%M'),
            datetime.now().strftime('%d/%m/%Y às %H:%M:%S'),
            requisicao.cliente.nome,
            float(requisicao.valor_total),
            float(requisicao.saldo_restante),
            requisicao.get_forma_pagamento_display(),
            # Adicionar linha do banco se for transferência
            f'''<tr>
                <td class="label">Banco:</td>
                <td class="value">{requisicao.banco}</td>
            </tr>''' if requisicao.forma_pagamento == 'transferencia' and hasattr(requisicao, 'banco') and requisicao.banco else '',
            'status-ativa' if requisicao.ativa else 'status-inativa',
            'ATIVA' if requisicao.ativa else 'INATIVA',
            requisicao.data_criacao.strftime('%d/%m/%Y às %H:%M:%S'),
            datetime.now().strftime('%d/%m/%Y às %H:%M:%S'),
            requisicao.id,
            getattr(requisicao, 'codigo', f'RS-{requisicao.id:06d}'),
            request.user.get_full_name() or request.user.username
        )
        
        # Gerar PDF
        result = io.BytesIO()
        pdf = pisa.pisaDocument(io.BytesIO(template_string.encode("UTF-8")), result)
        
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            filename = f'recibo_saldo_{requisicao.id:06d}_{requisicao.data_criacao.strftime("%Y%m%d")}.pdf'
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        else:
            messages.error(request, 'Erro ao gerar PDF do recibo.')
            return redirect('requisicoes_saldo')
            
    except Exception as e:
        messages.error(request, f'Erro ao gerar PDF: {str(e)}')
        return redirect('requisicoes_saldo')

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