from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Sum, Count, Q
from django.db import models
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction
from .models import Funcionario, Cliente, RequisicaoSenhas, Senha, RequisicaoSaldo, Movimento, Fecho
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
from itertools import chain
from operator import attrgetter
import json
import qrcode
import base64
from io import BytesIO
from PIL import Image

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
    
    # Total de clientes
    total_clientes = Cliente.objects.filter(empresa=empresa).count()
    
    # Total de requisições abertas (senhas + saldo)
    requisicoes_senhas_abertas = RequisicaoSenhas.objects.filter(
        empresa=empresa, 
        fecho__isnull=True
    ).count()
    
    requisicoes_saldo_abertas = RequisicaoSaldo.objects.filter(
        empresa=empresa,
        fecho__isnull=True
    ).count()
    
    total_requisicoes_abertas = requisicoes_senhas_abertas + requisicoes_saldo_abertas
    
    # Total valor de movimentos do mês atual
    hoje = timezone.now()
    inicio_mes = datetime(hoje.year, hoje.month, 1)
    fim_mes = datetime(hoje.year, hoje.month + 1, 1) if hoje.month < 12 else datetime(hoje.year + 1, 1, 1)
    
    total_movimentos_mes = Movimento.objects.filter(
        requisicao_saldo__empresa=empresa,
        data_criacao__gte=inicio_mes,
        data_criacao__lt=fim_mes
    ).aggregate(total=Sum('valor'))['total'] or 0
    
    # Total de senhas usadas no mês atual
    total_senhas_usadas_mes = Senha.objects.filter(
        empresa=empresa,
        usada=True,
        data_uso__gte=inicio_mes,
        data_uso__lt=fim_mes
    ).count()

    # Dados para gráfico de formas de pagamento
    # Contar requisições de senhas por forma de pagamento
    formas_pagamento_senhas = RequisicaoSenhas.objects.filter(
        empresa=empresa
    ).values('forma_pagamento').annotate(
        count=models.Count('id')
    )
    
    # Contar requisições de saldo por forma de pagamento
    formas_pagamento_saldo = RequisicaoSaldo.objects.filter(
        empresa=empresa
    ).values('forma_pagamento').annotate(
        count=models.Count('id')
    )
    
    # Consolidar dados de formas de pagamento
    pagamentos_consolidados = {}
    
    # Adicionar dados de senhas
    for item in formas_pagamento_senhas:
        forma = item['forma_pagamento']
        pagamentos_consolidados[forma] = pagamentos_consolidados.get(forma, 0) + item['count']
    
    # Adicionar dados de saldo
    for item in formas_pagamento_saldo:
        forma = item['forma_pagamento']
        pagamentos_consolidados[forma] = pagamentos_consolidados.get(forma, 0) + item['count']
    
    # Preparar dados para o gráfico
    formas_pagamento_labels = []
    formas_pagamento_data = []
    formas_pagamento_colors = []
    
    # Mapeamento de cores e labels
    pagamento_info = {
        'cash': {'label': 'Dinheiro (Cash)', 'color': '#28a745'},
        'transferencia': {'label': 'Transferência', 'color': '#007bff'},
        'pos': {'label': 'POS (Cartão)', 'color': '#ffc107'},
    }
    
    for forma, count in pagamentos_consolidados.items():
        info = pagamento_info.get(forma, {'label': forma.title(), 'color': '#6c757d'})
        formas_pagamento_labels.append(info['label'])
        formas_pagamento_data.append(count)
        formas_pagamento_colors.append(info['color'])

    # Dados para gráfico de clientes com mais requisições
    # Contar requisições de senhas por cliente
    requisicoes_senhas_por_cliente = RequisicaoSenhas.objects.filter(
        empresa=empresa
    ).values('cliente__nome').annotate(
        count=models.Count('id')
    )
    
    # Contar requisições de saldo por cliente
    requisicoes_saldo_por_cliente = RequisicaoSaldo.objects.filter(
        empresa=empresa
    ).values('cliente__nome').annotate(
        count=models.Count('id')
    )
    
    # Consolidar dados por cliente
    clientes_consolidados = {}
    
    # Adicionar dados de senhas
    for item in requisicoes_senhas_por_cliente:
        cliente = item['cliente__nome']
        clientes_consolidados[cliente] = clientes_consolidados.get(cliente, 0) + item['count']
    
    # Adicionar dados de saldo
    for item in requisicoes_saldo_por_cliente:
        cliente = item['cliente__nome']
        clientes_consolidados[cliente] = clientes_consolidados.get(cliente, 0) + item['count']
    
    # Ordenar clientes por número de requisições (top 10)
    clientes_ordenados = sorted(clientes_consolidados.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Preparar dados para o gráfico
    clientes_labels = [cliente[0] for cliente in clientes_ordenados]
    clientes_data = [cliente[1] for cliente in clientes_ordenados]

    context = {
        'total_clientes': total_clientes,
        'total_requisicoes_abertas': total_requisicoes_abertas,
        'requisicoes_senhas_abertas': requisicoes_senhas_abertas,
        'requisicoes_saldo_abertas': requisicoes_saldo_abertas,
        'total_movimentos_mes': total_movimentos_mes,
        'total_senhas_usadas_mes': total_senhas_usadas_mes,
        'mes_atual': hoje.strftime('%B %Y'),
        'formas_pagamento_labels': json.dumps(formas_pagamento_labels),
        'formas_pagamento_data': json.dumps(formas_pagamento_data),
        'formas_pagamento_colors': json.dumps(formas_pagamento_colors),
        'clientes_labels': json.dumps(clientes_labels),
        'clientes_data': json.dumps(clientes_data),
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
    
    # Usar annotate para contar ambos os tipos de requisições
    from django.db.models import Count
    
    clientes = Cliente.objects.filter(empresa=empresa).annotate(
        total_requisicoes=Count('requisicoes') + Count('requisicoes_saldo')
    ).order_by('-data_criacao')
    
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

@user_passes_test(is_gerente, login_url='/login/')
def extrato_cliente(request, cliente_id):
    """Extrato que só mostra dados que passaram por fecho - CORRIGIDO COM SENHAS E COMBUSTÍVEL PARA AMBOS"""
    cliente = get_object_or_404(Cliente, id=cliente_id)
    empresa = get_empresa_usuario(request.user)
    
    # Debug específico das senhas para ver os dados
    print("=== DEBUG DETALHADO DAS SENHAS ===")
    todas_senhas = Senha.objects.filter(
        cliente=cliente,
        empresa=empresa,
        usada=True
    ).select_related('requisicao', 'fecho')
    
    for senha in todas_senhas:
        print(f"Senha ID: {senha.id}")
        print(f"  - Código: {senha.codigo}")
        print(f"  - Usada: {senha.usada}")
        print(f"  - Tipo Combustível: {senha.tipo_combustivel}")
        print(f"  - Display Combustível: {senha.get_tipo_combustivel_display() if senha.tipo_combustivel else 'None'}")
        print(f"  - Data Uso: {senha.data_uso}")
        print(f"  - Fecho: {senha.fecho}")
        print(f"  - Tem Fecho: {senha.fecho is not None}")
        print("---")
    
    # Filtrar movimentos pela empresa através da requisicao_saldo
    # Verificar movimentos sem fecho
    movimentos_sem_fecho = Movimento.objects.filter(
        requisicao_saldo__cliente=cliente,
        requisicao_saldo__empresa=empresa,
        fecho__isnull=True
    )
    print(f"DEBUG: Movimentos sem fecho: {movimentos_sem_fecho.count()}")
    
    # Verificar movimentos com fecho  
    movimentos_com_fecho = Movimento.objects.filter(
        requisicao_saldo__cliente=cliente,
        requisicao_saldo__empresa=empresa,
        fecho__isnull=False
    )
    print(f"DEBUG: Movimentos com fecho: {movimentos_com_fecho.count()}")
    
    # Pegar APENAS créditos (RequisicaoSaldo) que foram fechados
    creditos = RequisicaoSaldo.objects.filter(
        cliente=cliente,
        empresa=empresa,
        ativa=True,
        fecho__isnull=False
    ).annotate(
        tipo=models.Value("credito", output_field=models.CharField())
    ).order_by('data_criacao')
    
    # Query melhorada para débitos com select_related
    debitos = Movimento.objects.filter(
        requisicao_saldo__cliente=cliente,
        requisicao_saldo__empresa=empresa,
        fecho__isnull=False
    ).select_related('requisicao_saldo', 'fecho').annotate(
        tipo=models.Value("debito", output_field=models.CharField())
    ).order_by('data_criacao')
    
    # Pegar APENAS requisições de senhas que foram fechadas
    requisicoes_senhas = RequisicaoSenhas.objects.filter(
        cliente=cliente,
        empresa=empresa,
        ativa=True,
        fecho__isnull=False
    ).annotate(
        tipo=models.Value("senha_requisicao", output_field=models.CharField())
    ).order_by('data_criacao')
    
    # Query mais específica para senhas usadas fechadas
    senhas_usadas = Senha.objects.filter(
        cliente=cliente,
        empresa=empresa,
        usada=True,
        fecho__isnull=False
    ).select_related('requisicao', 'fecho').annotate(
        tipo=models.Value("senha_usada", output_field=models.CharField())
    ).order_by('data_uso')
    
    print(f"DEBUG: Senhas usadas fechadas encontradas: {senhas_usadas.count()}")
    for senha in senhas_usadas:
        print(f"  Senha {senha.codigo}: tipo_combustivel={senha.tipo_combustivel}, display={senha.get_tipo_combustivel_display() if senha.tipo_combustivel else 'None'}")

    # Juntar todos os lançamentos numa única lista
    lancamentos = sorted(
        chain(creditos, debitos, requisicoes_senhas, senhas_usadas),
        key=lambda x: x.data_uso if hasattr(x, 'data_uso') and x.data_uso else x.data_criacao
    )

    extrato = []
    saldo = Decimal("0.00")

    def obter_forma_pagamento(lanc):
        """Função auxiliar para obter forma de pagamento com tratamento seguro do banco"""
        try:
            forma_pagamento = lanc.get_forma_pagamento_display()
            
            if lanc.forma_pagamento == 'transferencia' and hasattr(lanc, 'banco') and lanc.banco:
                if hasattr(lanc.banco, 'nome'):
                    forma_pagamento = f"Transferência - {lanc.banco.nome}"
                elif isinstance(lanc.banco, str):
                    forma_pagamento = f"Transferência - {lanc.banco}"
                else:
                    forma_pagamento = f"Transferência - {str(lanc.banco)}"
            
            return forma_pagamento
        except AttributeError:
            return "Não especificado"
        except Exception:
            return "Erro ao obter forma de pagamento"

    def obter_tipo_combustivel(lanc):
        """Função auxiliar para obter tipo de combustível de qualquer lançamento"""
        try:
            if hasattr(lanc, 'tipo_combustivel') and lanc.tipo_combustivel:
                return lanc.get_tipo_combustivel_display()
            return None
        except Exception:
            return lanc.tipo_combustivel if hasattr(lanc, 'tipo_combustivel') else None

    for i, lanc in enumerate(lancamentos):
        print(f"DEBUG: Processando lançamento {i+1}: Tipo={lanc.tipo}, ID={lanc.id}")
        
        if lanc.tipo == "credito":
            saldo += lanc.valor_total
            
            extrato.append({
                "data": lanc.data_criacao,
                "credito": lanc.valor_total,
                "descricao": f"Requisição de saldo {getattr(lanc, 'codigo', lanc.id)} (Fecho #{lanc.fecho.id})",
                "forma_pagamento": obter_forma_pagamento(lanc),
                "debito": None,
                "numero_requisicoes": f"Saldo #{lanc.id}",
                "gasolina_diesel": None,
                "valor": lanc.valor_total,
                "saldo": saldo,
                "tipo_combustivel": None,  # Requisições de saldo não têm tipo de combustível
                "fecho": lanc.fecho.id,
                "senha_usada": None,
                "senhas_restantes": None
            })
            
        elif lanc.tipo == "debito":
            saldo -= lanc.valor
            
            # Obter tipo de combustível do movimento de débito
            tipo_combustivel_display = obter_tipo_combustivel(lanc)
            
            extrato.append({
                "data": lanc.data_criacao,
                "credito": None,
                "descricao": getattr(lanc, 'descricao', None) or f"Débito - Movimento {getattr(lanc.requisicao_saldo, 'codigo', lanc.id)} (Fecho #{lanc.fecho.id})",
                "forma_pagamento": "Consumo",
                "debito": lanc.valor,
                "numero_requisicoes": f"Saldo #{lanc.requisicao_saldo.id}",
                "gasolina_diesel": None,
                "valor": lanc.valor,
                "saldo": saldo,
                "tipo_combustivel": tipo_combustivel_display,  # MOSTRAR COMBUSTÍVEL PARA DÉBITOS DE SALDO
                "fecho": lanc.fecho.id,
                "senha_usada": None,
                "senhas_restantes": None
            })
            
        elif lanc.tipo == "senha_requisicao":
            saldo += lanc.valor
            
            extrato.append({
                "data": lanc.data_criacao,
                "credito": lanc.valor,
                "descricao": f"Requisição de {lanc.senhas} senhas (Fecho #{lanc.fecho.id})",
                "forma_pagamento": obter_forma_pagamento(lanc),
                "debito": None,
                "numero_requisicoes": f"Senha #{lanc.id}",
                "gasolina_diesel": None,
                "valor": lanc.valor,
                "saldo": saldo,
                "tipo_combustivel": None,  # Requisições de senhas não têm tipo específico
                "fecho": lanc.fecho.id,
                "senha_usada": None
            })
            
        elif lanc.tipo == "senha_usada":
            # Calcular valor por senha
            valor_por_senha = lanc.requisicao.valor / lanc.requisicao.senhas
            saldo -= valor_por_senha
            
            # Obter tipo de combustível da senha usada
            combustivel_usado = obter_tipo_combustivel(lanc)
            
            extrato.append({
                "data": lanc.data_uso,
                "credito": None,
                "descricao": f"Senha usada: {lanc.codigo} (Fecho #{lanc.fecho.id})",
                "forma_pagamento": "Uso de senha",
                "debito": valor_por_senha,
                "numero_requisicoes": f"Senha #{lanc.requisicao.id}",
                "gasolina_diesel": None,
                "valor": valor_por_senha,
                "saldo": saldo,
                "tipo_combustivel": combustivel_usado,  # MOSTRAR COMBUSTÍVEL PARA SENHAS USADAS
                "fecho": lanc.fecho.id,
                "senha_usada": lanc.codigo
            })

    # Calcular totais
    total_creditos = sum([item["credito"] for item in extrato if item["credito"]], Decimal("0.00"))
    total_debitos = sum([item["debito"] for item in extrato if item["debito"]], Decimal("0.00"))
    saldo_atual = total_creditos - total_debitos

    # Contar dados pendentes (não fechados)
    dados_pendentes = {
        'requisicoes_senhas': RequisicaoSenhas.objects.filter(
            cliente=cliente, empresa=empresa, ativa=True, fecho__isnull=True
        ).count(),
        'requisicoes_saldo': RequisicaoSaldo.objects.filter(
            cliente=cliente, empresa=empresa, ativa=True, fecho__isnull=True
        ).count(),
        'movimentos': Movimento.objects.filter(
            requisicao_saldo__cliente=cliente,
            requisicao_saldo__empresa=empresa,
            fecho__isnull=True
        ).count(),
        'senhas_usadas': Senha.objects.filter(
            cliente=cliente, empresa=empresa, usada=True, fecho__isnull=True
        ).count()
    }
    
    total_pendentes = sum(dados_pendentes.values())

    return render(request, "gerente/extrato_cliente.html", {
        "cliente": cliente,
        "extrato": extrato,
        "total_creditos": total_creditos,
        "total_debitos": total_debitos,
        "saldo_atual": saldo_atual,
        "tem_movimentacao": len(extrato) > 0,
        "dados_pendentes": dados_pendentes,
        "total_pendentes": total_pendentes
    })

# ================================
# VIEWS DE REQUISIÇÕES SENHA
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def requisicoes(request):
    """Lista todas as requisições - Modificada para incluir dados do fecho"""
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    requisicoes = (
        RequisicaoSenhas.objects.filter(empresa=empresa, ativa=True)
        .select_related('cliente', 'fecho')  # ADICIONADO select_related para 'fecho'
        .prefetch_related('lista_senhas')
        .order_by('-data_criacao')
    )

    # Filtros opcionais
    status_filter = request.GET.get('status', '')
    fecho_filter = request.GET.get('fecho', '')  # NOVO FILTRO
    search = request.GET.get('search', '')

    if search:
        requisicoes = requisicoes.filter(
            Q(cliente__nome__icontains=search) |
            Q(id__icontains=search)
        )

    # Filtragem por fecho
    if fecho_filter == 'fechado':
        requisicoes = requisicoes.filter(fecho__isnull=False)
    elif fecho_filter == 'aberto':
        requisicoes = requisicoes.filter(fecho__isnull=True)

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
        'fecho_filter': fecho_filter,  # NOVO CONTEXTO
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
    """Editar requisição existente - Modificada para verificar fecho"""
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa, ativa=True)
    
    # VERIFICAÇÃO DE FECHO - NOVO
    if requisicao.fecho:
        messages.error(request, f'Não é possível editar a requisição #{requisicao.id} pois ela já foi fechada no fecho #{requisicao.fecho.id}.')
        return redirect('requisicoes')
    
    clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')
    
    if request.method == 'POST':
        try:
            cliente_id = request.POST.get('cliente')
            valor = request.POST.get('valor')
            quantidade_senhas = request.POST.get('quantidade_senhas')
            senhas_restantes = request.POST.get('senhas_restantes')
            forma_pagamento = request.POST.get('forma_pagamento')
            banco = request.POST.get('banco', '')
            
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
                requisicao.forma_pagamento = forma_pagamento
                requisicao.banco = banco if forma_pagamento == 'transferencia' else None
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
    """Deletar requisição (soft delete) - Modificada para verificar fecho"""
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa, ativa=True)
    
    # VERIFICAÇÃO DE FECHO - NOVO
    if requisicao.fecho:
        messages.error(request, f'Não é possível excluir a requisição #{requisicao.id} pois ela já foi fechada no fecho #{requisicao.fecho.id}.')
        return redirect('requisicoes')
    
    try:
        requisicao.ativa = False
        requisicao.save()
        messages.success(request, f'Requisição #{requisicao.id} removida com sucesso!')
    except Exception as e:
        messages.error(request, f'Erro ao remover requisição: {str(e)}')
    
    return redirect('requisicoes')

@user_passes_test(is_gerente, login_url='/login/')
def ver_senhas(request, requisicao_id):
    """
    View original atualizada para incluir contagem de senhas disponíveis
    """
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa)
    senhas = requisicao.lista_senhas.all()
    
    # Contar senhas disponíveis (não usadas)
    senhas_disponiveis_count = senhas.filter(usada=False).count()
    
    context = {
        'requisicao': requisicao,
        'senhas': senhas,
        'senhas_disponiveis_count': senhas_disponiveis_count,
    }
    
    return render(request, 'gerente/senhas.html', context)

# ================================
# VIEWS DE REQUISIÇÕES SALDO
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def requisicoes_saldo(request):
    """Lista todas as requisições de saldo - Modificada para incluir dados do fecho"""
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    requisicoes = (
        RequisicaoSaldo.objects.filter(empresa=empresa, ativa=True)
        .select_related('cliente', 'fecho')  # ADICIONADO select_related para 'fecho'
        .prefetch_related('movimentos')
        .order_by('-data_criacao')
    )

    # Filtros opcionais
    status_filter = request.GET.get('status', '')
    fecho_filter = request.GET.get('fecho', '')  # NOVO FILTRO
    search = request.GET.get('search', '')

    if search:
        requisicoes = requisicoes.filter(
            Q(cliente__nome__icontains=search) |
            Q(id__icontains=search) |
            Q(codigo__icontains=search)
        )

    # Filtragem por fecho
    if fecho_filter == 'fechado':
        requisicoes = requisicoes.filter(fecho__isnull=False)
    elif fecho_filter == 'aberto':
        requisicoes = requisicoes.filter(fecho__isnull=True)

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
        'fecho_filter': fecho_filter,  # NOVO CONTEXTO
        'total_valor': total_valor,
        'saldo_restante_total': saldo_restante_total,
    }
    return render(request, 'gerente/requisicoes_saldo.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def adicionar_requisicao_saldo(request, cliente_id=None):
    """View para adicionar nova requisição de saldo"""
    if request.method == 'POST':
        try:
            empresa = get_empresa_usuario(request.user)
            if not empresa:
                messages.error(request, 'Empresa não encontrada.')
                return redirect('login')
            
            # Obter dados do formulário com validação
            cliente_id_form = request.POST.get('cliente')
            valor_total_str = request.POST.get('valor_total', '0')
            forma_pagamento = request.POST.get('forma_pagamento')
            banco = request.POST.get('banco', '').strip()
            
            # Use cliente_id from URL if available, otherwise from form
            final_cliente_id = cliente_id if cliente_id else cliente_id_form
            
            # Validar campos obrigatórios
            if not final_cliente_id:
                messages.error(request, 'Cliente é obrigatório.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa),
                    'cliente_selecionado': cliente_id
                })
            
            if not forma_pagamento:
                messages.error(request, 'Forma de pagamento é obrigatória.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa),
                    'cliente_selecionado': cliente_id
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
                        'clientes': Cliente.objects.filter(empresa=empresa),
                        'cliente_selecionado': cliente_id
                    })
                    
            except (ValueError, InvalidOperation, TypeError) as e:
                messages.error(request, f'Valor total inválido: {valor_total_str}. Use apenas números.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa),
                    'cliente_selecionado': cliente_id
                })
            
            # Obter cliente
            try:
                cliente = Cliente.objects.get(id=int(final_cliente_id), empresa=empresa)
            except (Cliente.DoesNotExist, ValueError):
                messages.error(request, 'Cliente não encontrado.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa),
                    'cliente_selecionado': cliente_id
                })
            
            # Validar banco para transferência
            if forma_pagamento == 'transferencia' and not banco:
                messages.error(request, 'Nome do banco é obrigatório para transferência bancária.')
                return render(request, 'gerente/adicionar_req_saldo.html', {
                    'clientes': Cliente.objects.filter(empresa=empresa),
                    'cliente_selecionado': cliente_id
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
                'requisicao': requisicao,
                'cliente_selecionado': cliente_id
            })
            
        except Exception as e:
            # Log detalhado do erro
            print(f"Erro ao criar requisição de saldo: {str(e)}")
            print(f"Tipo do erro: {type(e)}")
            import traceback
            traceback.print_exc()
            
            messages.error(request, f'Erro ao criar requisição de saldo: {str(e)}')
            return render(request, 'gerente/adicionar_req_saldo.html', {
                'clientes': Cliente.objects.filter(empresa=empresa),
                'cliente_selecionado': cliente_id
            })
    
    else:
        # GET request - mostrar formulário
        empresa = get_empresa_usuario(request.user)
        if not empresa:
            messages.error(request, 'Empresa não encontrada.')
            return redirect('login')
            
        clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')
        
        # If cliente_id is provided in URL, get the cliente object
        cliente_selecionado = None
        if cliente_id:
            try:
                cliente_selecionado = Cliente.objects.get(id=cliente_id, empresa=empresa)
            except Cliente.DoesNotExist:
                messages.error(request, 'Cliente não encontrado.')
                return redirect('clientes')
        
        return render(request, 'gerente/adicionar_req_saldo.html', {
            'clientes': clientes,
            'cliente_selecionado': cliente_selecionado
        })


@user_passes_test(is_gerente, login_url='/login/')
def editar_requisicao_saldo(request, requisicao_id):
    """Editar requisição de saldo existente - Modificada para verificar fecho"""
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    requisicao = get_object_or_404(RequisicaoSaldo, id=requisicao_id, empresa=empresa, ativa=True)
    
    # VERIFICAÇÃO DE FECHO - NOVO
    if requisicao.fecho:
        messages.error(request, f'Não é possível editar a requisição de saldo #{requisicao.id} pois ela já foi fechada no fecho #{requisicao.fecho.id}.')
        return redirect('requisicoes_saldo')
    
    clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')
    
    if request.method == 'POST':
        try:
            cliente_id = request.POST.get('cliente')
            valor_total = request.POST.get('valor_total')
            forma_pagamento = request.POST.get('forma_pagamento')
            banco = request.POST.get('banco', '')
            
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
            requisicao.forma_pagamento = forma_pagamento
            requisicao.banco = banco if forma_pagamento == 'transferencia' else None
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
    """Deletar requisição de saldo (soft delete) - Modificada para verificar fecho"""
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    requisicao = get_object_or_404(RequisicaoSaldo, id=requisicao_id, empresa=empresa, ativa=True)
    
    # VERIFICAÇÃO DE FECHO - NOVO
    if requisicao.fecho:
        messages.error(request, f'Não é possível excluir a requisição de saldo #{requisicao.id} pois ela já foi fechada no fecho #{requisicao.fecho.id}.')
        return redirect('requisicoes_saldo')
    
    try:
        requisicao.ativa = False
        requisicao.save()
        messages.success(request, f'Requisição de saldo #{requisicao.id} removida com sucesso!')
    except Exception as e:
        messages.error(request, f'Erro ao remover requisição de saldo: {str(e)}')
    
    return redirect('requisicoes_saldo')

# ================================================
# VIEWS ADICIONAIS (Recibos, Extratos, Fecho, etc)
# ================================================

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
def imprimir_qr_codes(request, requisicao_id):
    """
    Gera e exibe QR Codes para todas as senhas não usadas de uma requisição
    """
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa)
    senhas_nao_usadas = requisicao.lista_senhas.filter(usada=False)
    
    # Gerar QR codes para cada senha não usada
    senhas_com_qr = []
    for senha in senhas_nao_usadas:
        qr_code_base64 = gerar_qr_code(senha.codigo)
        senha.qr_code_base64 = qr_code_base64
        senhas_com_qr.append(senha)
    
    context = {
        'requisicao': requisicao,
        'senhas_nao_usadas': senhas_com_qr,
        'data_geracao': timezone.now().strftime("%d/%m/%Y %H:%M")
    }
    
    return render(request, 'gerente/qr_codes.html', context)

def gerar_qr_code(texto):
    """
    Gera um QR Code em base64 para o texto fornecido
    """
    # Configurar o QR Code
    qr = qrcode.QRCode(
        version=1,  # Controla o tamanho do QR Code
        error_correction=qrcode.constants.ERROR_CORRECT_L,  # Correção de erro baixa
        box_size=8,  # Tamanho de cada "caixa" do QR Code
        border=4,   # Tamanho da borda
    )
    
    # Adicionar dados ao QR Code
    qr.add_data(texto)
    qr.make(fit=True)
    
    # Criar imagem do QR Code
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Converter para base64
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    # Codificar em base64
    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    return qr_code_base64


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
    
@user_passes_test(is_gerente, login_url='/login/')
def fecho(request):
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    fechos = Fecho.objects.filter(empresa=empresa).order_by('-data')
    
    context = {
        'fechos': fechos,
    }
    return render(request, 'gerente/fecho.html', context)

@user_passes_test(is_gerente, login_url='/login/')
def fazer_fecho(request):
    """Realizar o fecho - marca TODOS os movimentos (receitas e débitos) como fechados"""
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    try:
        with transaction.atomic():
            # CONTAR DADOS QUE SERÃO FECHADOS (ANTES de criar o fecho)
            
            # 1. Requisições de senhas não fechadas (RECEITAS)
            requisicoes_senhas_nao_fechadas = RequisicaoSenhas.objects.filter(
                empresa=empresa, 
                ativa=True, 
                fecho__isnull=True
            ).count()
            
            # 2. Requisições de saldo não fechadas (RECEITAS) 
            requisicoes_saldo_nao_fechadas = RequisicaoSaldo.objects.filter(
                empresa=empresa, 
                ativa=True, 
                fecho__isnull=True
            ).count()
            
            # 3. CORREÇÃO: Movimentos de débito não fechados (SAÍDAS DE SALDO)
            # Filtrar pela empresa através da requisicao_saldo
            movimentos_nao_fechados = Movimento.objects.filter(
                requisicao_saldo__empresa=empresa,  # CORREÇÃO: filtrar pela empresa através da requisicao_saldo
                fecho__isnull=True
            ).count()
            
            # 4. Senhas usadas de requisições não fechadas (DÉBITOS DE SENHAS)
            senhas_usadas_nao_fechadas = Senha.objects.filter(
                empresa=empresa,
                usada=True,
                data_uso__isnull=False,  # Garantir que tem data de uso
                fecho__isnull=True  # CORREÇÃO: senhas não fechadas individualmente
            ).count()
            
            # Verificar se há dados para fechar
            total_dados_pendentes = (
                requisicoes_senhas_nao_fechadas + 
                requisicoes_saldo_nao_fechadas + 
                movimentos_nao_fechados +
                senhas_usadas_nao_fechadas
            )
            
            print(f"DEBUG FECHO: Dados pendentes - Req.Senhas: {requisicoes_senhas_nao_fechadas}, Req.Saldo: {requisicoes_saldo_nao_fechadas}, Movimentos: {movimentos_nao_fechados}, Senhas: {senhas_usadas_nao_fechadas}")
            
            if total_dados_pendentes == 0:
                messages.warning(request, 'Não há dados pendentes para fazer fecho.')
                return redirect('fecho')
            
            # CRIAR NOVO FECHO
            novo_fecho = Fecho.objects.create(empresa=empresa)
            print(f"DEBUG FECHO: Criado fecho #{novo_fecho.id}")
            
            # FECHAR REQUISIÇÕES DE SENHAS (RECEITAS)
            req_senhas_fechadas = RequisicaoSenhas.objects.filter(
                empresa=empresa, 
                ativa=True, 
                fecho__isnull=True
            ).update(fecho=novo_fecho)
            print(f"DEBUG FECHO: Requisições de senhas fechadas: {req_senhas_fechadas}")
            
            # FECHAR REQUISIÇÕES DE SALDO (RECEITAS)
            req_saldo_fechadas = RequisicaoSaldo.objects.filter(
                empresa=empresa, 
                ativa=True, 
                fecho__isnull=True
            ).update(fecho=novo_fecho)
            print(f"DEBUG FECHO: Requisições de saldo fechadas: {req_saldo_fechadas}")
            
            # CORREÇÃO: FECHAR MOVIMENTOS DE DÉBITO (SAÍDAS DE SALDO)
            # Filtrar pela empresa através da requisicao_saldo
            movimentos_fechados = Movimento.objects.filter(
                requisicao_saldo__empresa=empresa,  # CORREÇÃO: filtrar pela empresa
                fecho__isnull=True
            ).update(fecho=novo_fecho)
            print(f"DEBUG FECHO: Movimentos fechados: {movimentos_fechados}")
            
            # FECHAR SENHAS USADAS INDIVIDUALMENTE
            senhas_fechadas = Senha.objects.filter(
                empresa=empresa,
                usada=True,
                data_uso__isnull=False,
                fecho__isnull=True  # CORREÇÃO: senhas não fechadas individualmente
            ).update(fecho=novo_fecho)
            print(f"DEBUG FECHO: Senhas fechadas: {senhas_fechadas}")
            
            # DEBUG: Verificar se os movimentos foram realmente fechados
            movimentos_ainda_pendentes = Movimento.objects.filter(
                requisicao_saldo__empresa=empresa,
                fecho__isnull=True
            ).count()
            print(f"DEBUG FECHO: Movimentos ainda pendentes após fecho: {movimentos_ainda_pendentes}")
            
            messages.success(request, 
                f'Fecho #{novo_fecho.id} realizado com sucesso! '
                f'{total_dados_pendentes} registros fechados: '
                f'{req_senhas_fechadas} req. senhas, '
                f'{req_saldo_fechadas} req. saldo, '
                f'{movimentos_fechados} movimentos, '
                f'{senhas_fechadas} senhas usadas.'
            )
            
    except Exception as e:
        print(f"ERRO FECHO: {str(e)}")
        import traceback
        traceback.print_exc()
        messages.error(request, f'Erro ao realizar fecho: {str(e)}')
    
    return redirect('fecho')


# ================================
# FUNÇÃO AUXILIAR PARA VERIFICAR SE PODE EDITAR/EXCLUIR
# ================================
@user_passes_test(is_gerente, login_url='/login/')
def pode_editar_requisicao(requisicao):
    """
    Função auxiliar para verificar se uma requisição pode ser editada/excluída
    Retorna True se não tiver fecho, False caso contrário
    """
    return requisicao.fecho is None

@user_passes_test(is_gerente, login_url='/login/')
def pode_editar_requisicao_saldo(requisicao_saldo):
    """
    Função auxiliar para verificar se uma requisição de saldo pode ser editada/excluída
    Retorna True se não tiver fecho, False caso contrário
    """
    return requisicao_saldo.fecho is None

@user_passes_test(is_gerente, login_url='/login/')
def preview_fecho(request):
    """View para visualizar o que será fechado antes de confirmar - INCLUINDO DÉBITOS"""
    empresa = get_empresa_usuario(request.user)
    if not empresa:
        messages.error(request, 'Empresa não encontrada.')
        return redirect('login')
    
    # RECEITAS (ENTRADAS) - Dados ainda não fechados
    requisicoes_senhas_abertas = RequisicaoSenhas.objects.filter(
        empresa=empresa, 
        ativa=True, 
        fecho__isnull=True
    ).select_related('cliente')
    
    requisicoes_saldo_abertas = RequisicaoSaldo.objects.filter(
        empresa=empresa, 
        ativa=True, 
        fecho__isnull=True
    ).select_related('cliente')
    
    # DÉBITOS (SAÍDAS) - Dados ainda não fechados
    movimentos_abertos = Movimento.objects.filter(
        empresa=empresa, 
        fecho__isnull=True
    ).select_related('requisicao_saldo__cliente', 'funcionario')
    
    # SENHAS USADAS - Dados ainda não fechados
    senhas_usadas_abertas = Senha.objects.filter(
        empresa=empresa,
        usada=True,
        data_uso__isnull=False,
        # Senhas usadas que ainda não foram fechadas individualmente
        # (removemos a dependência do fecho da requisição)
    ).select_related('requisicao__cliente', 'funcionario_uso').order_by('-data_uso')
    
    # Calcular totais financeiros
    total_valor_senhas = sum(r.valor for r in requisicoes_senhas_abertas)
    total_valor_saldo = sum(r.valor_total for r in requisicoes_saldo_abertas) 
    total_debitos_saldo = sum(m.valor for m in movimentos_abertos)
    # Senhas usadas não têm valor individual, mas podemos contar
    
    # TOTAL DE REGISTROS
    total_registros = (
        len(requisicoes_senhas_abertas) + 
        len(requisicoes_saldo_abertas) + 
        len(movimentos_abertos) +
        len(senhas_usadas_abertas)
    )
    
    context = {
        # RECEITAS
        'requisicoes_senhas_abertas': requisicoes_senhas_abertas,
        'requisicoes_saldo_abertas': requisicoes_saldo_abertas,
        
        # DÉBITOS  
        'movimentos_abertos': movimentos_abertos,
        'senhas_usadas_abertas': senhas_usadas_abertas,
        
        # TOTAIS
        'total_valor_senhas': total_valor_senhas,
        'total_valor_saldo': total_valor_saldo,
        'total_debitos_saldo': total_debitos_saldo,
        'total_entradas': total_valor_senhas + total_valor_saldo,
        'total_saidas': total_debitos_saldo,  # Senhas não têm valor
        'total_registros': total_registros,
        
        # CONTADORES
        'count_req_senhas': len(requisicoes_senhas_abertas),
        'count_req_saldo': len(requisicoes_saldo_abertas), 
        'count_movimentos': len(movimentos_abertos),
        'count_senhas_usadas': len(senhas_usadas_abertas),
    }
    
    return render(request, 'gerente/preview_fecho.html', context)

# ================================
# SIGNALS PARA AUDITORIA (OPCIONAL)
# ================================

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError

@receiver(pre_save, sender=RequisicaoSenhas)
def verificar_edicao_requisicao_senhas(sender, instance, **kwargs):
    """Impede edição de requisições fechadas"""
    if instance.pk:  # Se está atualizando (não criando)
        try:
            original = RequisicaoSenhas.objects.get(pk=instance.pk)
            if original.fecho and original.fecho != instance.fecho:
                raise ValidationError("Não é possível editar uma requisição já fechada")
        except RequisicaoSenhas.DoesNotExist:
            pass

@receiver(pre_save, sender=RequisicaoSaldo)
def verificar_edicao_requisicao_saldo(sender, instance, **kwargs):
    """Impede edição de requisições de saldo fechadas"""
    if instance.pk:  # Se está atualizando (não criando)
        try:
            original = RequisicaoSaldo.objects.get(pk=instance.pk)
            if original.fecho and original.fecho != instance.fecho:
                raise ValidationError("Não é possível editar uma requisição de saldo já fechada")
        except RequisicaoSaldo.DoesNotExist:
            pass

# ================================
# VIEWS AJAX
# ================================

@user_passes_test(is_gerente, login_url='/login/')
def ajax_pode_editar_requisicao(request, requisicao_id):
    """AJAX para verificar se uma requisição pode ser editada"""
    try:
        empresa = get_empresa_usuario(request.user)
        if not empresa:
            return JsonResponse({'pode_editar': False, 'motivo': 'Empresa não encontrada'})
        
        requisicao = get_object_or_404(RequisicaoSenhas, id=requisicao_id, empresa=empresa)
        
        pode_editar = requisicao.fecho is None
        motivo = "Requisição já foi fechada" if not pode_editar else "Pode editar"
        
        return JsonResponse({
            'pode_editar': pode_editar,
            'motivo': motivo,
            'fecho_id': requisicao.fecho.id if requisicao.fecho else None
        })
        
    except Exception as e:
        return JsonResponse({'pode_editar': False, 'motivo': str(e)})

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
   
# ================================
# MIDDLEWARE/DECORADOR OPCIONAL PARA VERIFICAÇÃO DE FECHO
# ================================

from functools import wraps

@user_passes_test(is_gerente, login_url='/login/')
def verificar_fecho_requisicao(model_class, redirect_url):
    """
    Decorador para verificar se uma requisição pode ser editada/excluída
    
    Args:
        model_class: RequisicaoSenhas ou RequisicaoSaldo
        redirect_url: URL para redirecionar em caso de erro
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if 'requisicao_id' in kwargs:
                requisicao_id = kwargs['requisicao_id']
                try:
                    empresa = get_empresa_usuario(request.user)
                    if not empresa:
                        messages.error(request, 'Empresa não encontrada.')
                        return redirect('login')
                    
                    requisicao = get_object_or_404(model_class, id=requisicao_id, empresa=empresa, ativa=True)
                    
                    if requisicao.fecho:
                        model_name = model_class._meta.verbose_name
                        messages.error(request, 
                            f'Não é possível alterar {model_name} #{requisicao.id} pois já foi fechada no fecho #{requisicao.fecho.id}.')
                        return redirect(redirect_url)
                        
                except model_class.DoesNotExist:
                    messages.error(request, f'{model_class._meta.verbose_name} não encontrada.')
                    return redirect(redirect_url)
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

# Exemplo de uso do decorador:
# @verificar_fecho_requisicao(RequisicaoSenhas, 'requisicoes')
# def editar_requisicao(request, requisicao_id):
#     # sua view aqui