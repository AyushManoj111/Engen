from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Sum, Count, Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.utils import timezone
from .models import Funcionario, Cliente, Requisicao, HistoricoSenha
import logging

# Configurar logging
logger = logging.getLogger(__name__)

def is_superuser(user):
    """Verifica se o usuário é superuser"""
    return user.is_superuser

def login_view(request):
    """View para página de login - apenas para superusuários"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Autentica o usuário
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Verifica se o usuário é superusuário
            if user.is_superuser:
                login(request, user)
                # Sempre redireciona para dashboard, ignorando o parâmetro 'next'
                return redirect('dashboard')
            else:
                messages.error(request, 'Acesso negado. Apenas administradores podem acessar o sistema.')
        else:
            messages.error(request, 'Username ou senha incorretos')
    
    return render(request, 'gerente/login.html')

@user_passes_test(is_superuser, login_url='/login/')
def dashboard_view(request):
    total_funcionarios = Funcionario.objects.count()
    total_clientes = Cliente.objects.count()
    total_requisicoes = Requisicao.objects.count()
    requisicoes_pendentes = Requisicao.objects.filter(senhas_restantes__gt=0).count()

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
    return redirect('login')

# ================================
# VIEWS DE FUNCIONÁRIOS
# ================================

@user_passes_test(is_superuser, login_url='/login/')
def funcionarios(request):
    """Lista todos os funcionários"""
    funcionarios = Funcionario.objects.filter(ativo=True).order_by('-data_criacao')
    
    # Filtros opcionais
    search = request.GET.get('search', '')
    if search:
        funcionarios = funcionarios.filter(
            Q(nome__icontains=search) | 
            Q(email__icontains=search)
        )
    
    context = {
        'funcionarios': funcionarios,
        'search': search,
    }
    return render(request, 'gerente/funcionarios.html', context)


@user_passes_test(is_superuser, login_url='/login/')
def adicionar_funcionario(request):
    """Adicionar novo funcionário"""
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
                return render(request, 'funcionarios/adicionar_funcionario.html')
            
            # Verificar se email já existe
            if Funcionario.objects.filter(email=email).exists():
                messages.error(request, 'Já existe um funcionário com este email.')
                return render(request, 'gerente/adicionar_funcionario.html')
            
            # Criar funcionário
            funcionario = Funcionario.objects.create(
                nome=nome,
                email=email,
                password=password,  # Em produção, usar hash
                contacto=contacto if contacto else None,
                morada=morada if morada else None,
            )
            
            messages.success(request, f'Funcionário "{funcionario.nome}" adicionado com sucesso!')
            return redirect('funcionarios')
            
        except Exception as e:
            messages.error(request, f'Erro ao adicionar funcionário: {str(e)}')
    
    return render(request, 'gerente/adicionar_funcionario.html')


@user_passes_test(is_superuser, login_url='/login/')
def editar_funcionario(request, funcionario_id):
    """Editar funcionário existente"""
    funcionario = get_object_or_404(Funcionario, id=funcionario_id, ativo=True)
    
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
                return render(request, 'funcionarios/editar_funcionario.html', {'funcionario': funcionario})
            
            # Verificar se email já existe (exceto o atual)
            if Funcionario.objects.filter(email=email).exclude(id=funcionario.id).exists():
                messages.error(request, 'Já existe outro funcionário com este email.')
                return render(request, 'funcionarios/editar_funcionario.html', {'funcionario': funcionario})
            
            # Atualizar funcionário
            funcionario.nome = nome
            funcionario.email = email
            if password:  # Só atualiza se nova senha foi fornecida
                funcionario.password = password
            funcionario.contacto = contacto if contacto else None
            funcionario.morada = morada if morada else None
            funcionario.save()
            
            messages.success(request, f'Funcionário "{funcionario.nome}" atualizado com sucesso!')
            return redirect('funcionarios')
            
        except Exception as e:
            messages.error(request, f'Erro ao atualizar funcionário: {str(e)}')
    
    return render(request, 'gerente/editar_funcionario.html', {'funcionario': funcionario})


@user_passes_test(is_superuser, login_url='/login/')
def deletar_funcionario(request, funcionario_id):
    """Deletar funcionário (soft delete)"""
    funcionario = get_object_or_404(Funcionario, id=funcionario_id, ativo=True)
    
    try:
        funcionario.ativo = False
        funcionario.save()
        messages.success(request, f'Funcionário "{funcionario.nome}" removido com sucesso!')
    except Exception as e:
        messages.error(request, f'Erro ao remover funcionário: {str(e)}')
    
    return redirect('funcionarios')


# ================================
# VIEWS DE CLIENTES
# ================================

@user_passes_test(is_superuser, login_url='/login/')
def clientes(request):
    """Lista todos os clientes"""
    clientes = Cliente.objects.filter(ativo=True).prefetch_related('requisicoes').order_by('-data_criacao')
    
    # Filtros opcionais
    search = request.GET.get('search', '')
    if search:
        clientes = clientes.filter(
            Q(nome__icontains=search) | 
            Q(contacto__icontains=search) |
            Q(endereco__icontains=search)
        )
    
    context = {
        'clientes': clientes,
        'search': search,
    }
    return render(request, 'gerente/clientes.html', context)


@user_passes_test(is_superuser, login_url='/login/')
def adicionar_cliente(request):
    """Adicionar novo cliente"""
    if request.method == 'POST':
        try:
            nome = request.POST.get('nome', '').strip()
            contacto = request.POST.get('contacto', '').strip()
            endereco = request.POST.get('endereco', '').strip()
            
            # Validações básicas
            if not nome:
                messages.error(request, 'Nome é obrigatório.')
                return render(request, 'clientes/adicionar_cliente.html')
            
            # Criar cliente
            cliente = Cliente.objects.create(
                nome=nome,
                contacto=contacto if contacto else None,
                endereco=endereco if endereco else None,
            )
            
            messages.success(request, f'Cliente "{cliente.nome}" adicionado com sucesso!')
            return redirect('clientes')
            
        except Exception as e:
            messages.error(request, f'Erro ao adicionar cliente: {str(e)}')
    
    return render(request, 'gerente/adicionar_cliente.html')


@user_passes_test(is_superuser, login_url='/login/')
def editar_cliente(request, cliente_id):
    """Editar cliente existente"""
    cliente = get_object_or_404(Cliente, id=cliente_id, ativo=True)
    
    if request.method == 'POST':
        try:
            nome = request.POST.get('nome', '').strip()
            contacto = request.POST.get('contacto', '').strip()
            endereco = request.POST.get('endereco', '').strip()
            
            # Validações básicas
            if not nome:
                messages.error(request, 'Nome é obrigatório.')
                return render(request, 'clientes/editar_cliente.html', {'cliente': cliente})
            
            # Atualizar cliente
            cliente.nome = nome
            cliente.contacto = contacto if contacto else None
            cliente.endereco = endereco if endereco else None
            cliente.save()
            
            messages.success(request, f'Cliente "{cliente.nome}" atualizado com sucesso!')
            return redirect('clientes')
            
        except Exception as e:
            messages.error(request, f'Erro ao atualizar cliente: {str(e)}')
    
    return render(request, 'gerente/editar_cliente.html', {'cliente': cliente})


@user_passes_test(is_superuser, login_url='/login/')
def deletar_cliente(request, cliente_id):
    """Deletar cliente (soft delete)"""
    cliente = get_object_or_404(Cliente, id=cliente_id, ativo=True)
    
    try:
        # Verificar se cliente tem requisições ativas
        requisicoes_ativas = cliente.requisicoes.filter(ativa=True).count()
        if requisicoes_ativas > 0:
            messages.warning(request, f'Cliente "{cliente.nome}" possui {requisicoes_ativas} requisição(ões) ativa(s). Remova-as primeiro.')
            return redirect('clientes')
        
        cliente.ativo = False
        cliente.save()
        messages.success(request, f'Cliente "{cliente.nome}" removido com sucesso!')
    except Exception as e:
        messages.error(request, f'Erro ao remover cliente: {str(e)}')
    
    return redirect('clientes')


# ================================
# VIEWS DE REQUISIÇÕES
# ================================

@user_passes_test(is_superuser, login_url='/login/')
def requisicoes(request):
    """Lista todas as requisições"""
    requisicoes = Requisicao.objects.filter(ativa=True).select_related('cliente').order_by('-data_criacao')
    
    # Filtros opcionais
    status_filter = request.GET.get('status', '')
    search = request.GET.get('search', '')
    
    if search:
        requisicoes = requisicoes.filter(
            Q(cliente__nome__icontains=search) |
            Q(id__icontains=search)
        )
    
    if status_filter:
        if status_filter == 'completo':
            requisicoes = requisicoes.filter(senhas_restantes=0)
        elif status_filter == 'baixo':
            requisicoes = requisicoes.filter(senhas_restantes__gt=0, senhas_restantes__lte=5)
        elif status_filter == 'medio':
            requisicoes = requisicoes.filter(senhas_restantes__gt=5, senhas_restantes__lte=15)
        elif status_filter == 'alto':
            requisicoes = requisicoes.filter(senhas_restantes__gt=15)
    
    # Estatísticas
    stats = requisicoes.aggregate(
        total_valor=Sum('valor'),
        total_senhas=Sum('senhas'),
        senhas_restantes_total=Sum('senhas_restantes')
    )
    
    context = {
        'requisicoes': requisicoes,
        'search': search,
        'status_filter': status_filter,
        'total_valor': stats['total_valor'] or 0,
        'total_senhas': stats['total_senhas'] or 0,
        'senhas_restantes_total': stats['senhas_restantes_total'] or 0,
    }
    return render(request, 'gerente/requisicoes.html', context)


@user_passes_test(is_superuser, login_url='/login/')
def adicionar_requisicao(request):
    """Adicionar nova requisição"""
    clientes = Cliente.objects.filter(ativo=True).order_by('nome')
    
    if request.method == 'POST':
        try:
            cliente_id = request.POST.get('cliente')
            valor = request.POST.get('valor')
            quantidade_senhas = request.POST.get('quantidade_senhas')
            observacoes = request.POST.get('observacoes', '').strip()
            
            # Validações básicas
            if not cliente_id or not valor or not quantidade_senhas:
                messages.error(request, 'Cliente, valor e quantidade de senhas são obrigatórios.')
                return render(request, 'requisicoes/adicionar_requisicao.html', {'clientes': clientes})
            
            try:
                valor = float(valor)
                quantidade_senhas = int(quantidade_senhas)
            except ValueError:
                messages.error(request, 'Valor e quantidade devem ser números válidos.')
                return render(request, 'requisicoes/adicionar_requisicao.html', {'clientes': clientes})
            
            if valor <= 0 or quantidade_senhas <= 0:
                messages.error(request, 'Valor e quantidade devem ser maiores que zero.')
                return render(request, 'requisicoes/adicionar_requisicao.html', {'clientes': clientes})
            
            # Buscar cliente
            cliente = get_object_or_404(Cliente, id=cliente_id, ativo=True)
            
            # Criar requisição
            requisicao = Requisicao.objects.create(
                cliente=cliente,
                valor=valor,
                senhas=quantidade_senhas,
                senhas_restantes=quantidade_senhas,
                observacoes=observacoes if observacoes else None,
                funcionario_responsavel=None  # Pode ser definido depois
            )
            
            # Registrar no histórico
            HistoricoSenha.objects.create(
                requisicao=requisicao,
                quantidade=quantidade_senhas,
                motivo="Criação da requisição",
                funcionario=None
            )
            
            messages.success(request, f'Requisição #{requisicao.id} criada com sucesso para {cliente.nome}!')
            return redirect('requisicoes')
            
        except Exception as e:
            messages.error(request, f'Erro ao criar requisição: {str(e)}')
    
    context = {
        'clientes': clientes,
    }
    return render(request, 'gerente/adicionar_requisicao.html', context)


@user_passes_test(is_superuser, login_url='/login/')
def editar_requisicao(request, requisicao_id):
    """Editar requisição existente"""
    requisicao = get_object_or_404(Requisicao, id=requisicao_id, ativa=True)
    clientes = Cliente.objects.filter(ativo=True).order_by('nome')
    
    if request.method == 'POST':
        try:
            cliente_id = request.POST.get('cliente')
            valor = request.POST.get('valor')
            quantidade_senhas = request.POST.get('quantidade_senhas')
            senhas_restantes = request.POST.get('senhas_restantes')
            observacoes = request.POST.get('observacoes', '').strip()
            
            # Validações básicas
            if not cliente_id or not valor or not quantidade_senhas:
                messages.error(request, 'Cliente, valor e quantidade de senhas são obrigatórios.')
                return render(request, 'requisicoes/editar_requisicao.html', {
                    'requisicao': requisicao,
                    'clientes': clientes
                })
            
            try:
                valor = float(valor)
                quantidade_senhas = int(quantidade_senhas)
                senhas_restantes = int(senhas_restantes) if senhas_restantes else 0
            except ValueError:
                messages.error(request, 'Valores devem ser números válidos.')
                return render(request, 'requisicoes/editar_requisicao.html', {
                    'requisicao': requisicao,
                    'clientes': clientes
                })
            
            if valor <= 0 or quantidade_senhas <= 0:
                messages.error(request, 'Valor e quantidade devem ser maiores que zero.')
                return render(request, 'requisicoes/editar_requisicao.html', {
                    'requisicao': requisicao,
                    'clientes': clientes
                })
            
            if senhas_restantes > quantidade_senhas:
                messages.error(request, 'Senhas restantes não podem ser maiores que o total.')
                return render(request, 'requisicoes/editar_requisicao.html', {
                    'requisicao': requisicao,
                    'clientes': clientes
                })
            
            # Buscar cliente
            cliente = get_object_or_404(Cliente, id=cliente_id, ativo=True)
            
            # Verificar mudanças nas senhas restantes para histórico
            senhas_restantes_anterior = requisicao.senhas_restantes
            diferenca_senhas = senhas_restantes - senhas_restantes_anterior
            
            # Atualizar requisição
            requisicao.cliente = cliente
            requisicao.valor = valor
            requisicao.senhas = quantidade_senhas
            requisicao.senhas_restantes = senhas_restantes
            requisicao.observacoes = observacoes if observacoes else None
            requisicao.save()
            
            # Registrar mudança no histórico se houve alteração
            if diferenca_senhas != 0:
                motivo = f"Edição da requisição - Ajuste de senhas"
                HistoricoSenha.objects.create(
                    requisicao=requisicao,
                    quantidade=diferenca_senhas,
                    motivo=motivo,
                    funcionario=None
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


@user_passes_test(is_superuser, login_url='/login/')
def deletar_requisicao(request, requisicao_id):
    """Deletar requisição (soft delete)"""
    requisicao = get_object_or_404(Requisicao, id=requisicao_id, ativa=True)
    
    try:
        requisicao.ativa = False
        requisicao.save()
        
        # Registrar no histórico
        HistoricoSenha.objects.create(
            requisicao=requisicao,
            quantidade=0,
            motivo="Requisição removida do sistema",
            funcionario=None
        )
        
        messages.success(request, f'Requisição #{requisicao.id} removida com sucesso!')
    except Exception as e:
        messages.error(request, f'Erro ao remover requisição: {str(e)}')
    
    return redirect('requisicoes')


# ================================
# VIEWS ADICIONAIS
# ================================

@user_passes_test(is_superuser, login_url='/login/')
def dashboard(request):
    """Dashboard principal com estatísticas"""
    # Estatísticas gerais
    stats = {
        'total_funcionarios': Funcionario.objects.filter(ativo=True).count(),
        'total_clientes': Cliente.objects.filter(ativo=True).count(),
        'total_requisicoes': Requisicao.objects.filter(ativa=True).count(),
        'requisicoes_concluidas': Requisicao.objects.filter(ativa=True, senhas_restantes=0).count(),
    }
    
    # Requisições por status
    requisicoes_status = {
        'alto': Requisicao.objects.filter(ativa=True, senhas_restantes__gt=15).count(),
        'medio': Requisicao.objects.filter(ativa=True, senhas_restantes__gt=5, senhas_restantes__lte=15).count(),
        'baixo': Requisicao.objects.filter(ativa=True, senhas_restantes__gt=0, senhas_restantes__lte=5).count(),
        'completo': Requisicao.objects.filter(ativa=True, senhas_restantes=0).count(),
    }
    
    # Valores totais
    valores = Requisicao.objects.filter(ativa=True).aggregate(
        valor_total=Sum('valor'),
        senhas_total=Sum('senhas'),
        senhas_restantes_total=Sum('senhas_restantes')
    )
    
    # Últimas requisições
    ultimas_requisicoes = Requisicao.objects.filter(ativa=True).select_related('cliente').order_by('-data_criacao')[:5]
    
    # Clientes com mais requisições
    top_clientes = Cliente.objects.filter(ativo=True).annotate(
        num_requisicoes=Count('requisicoes', filter=Q(requisicoes__ativa=True))
    ).order_by('-num_requisicoes')[:5]
    
    context = {
        'stats': stats,
        'requisicoes_status': requisicoes_status,
        'valores': valores,
        'ultimas_requisicoes': ultimas_requisicoes,
        'top_clientes': top_clientes,
    }
    return render(request, 'gerente/dashboard.html', context)


@user_passes_test(is_superuser, login_url='/login/')
def requisicoes_cliente(request, cliente_id):
    """Lista todas as requisições de um cliente específico"""
    cliente = get_object_or_404(Cliente, id=cliente_id, ativo=True)
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


# ================================
# VIEWS AJAX (OPCIONAIS)
# ================================

@user_passes_test(is_superuser, login_url='/login/')
def ajax_cliente_info(request, cliente_id):
    """Retorna informações do cliente em JSON"""
    try:
        cliente = get_object_or_404(Cliente, id=cliente_id, ativo=True)
        data = {
            'id': cliente.id,
            'nome': cliente.nome,
            'contacto': cliente.contacto,
            'endereco': cliente.endereco,
            'total_requisicoes': cliente.total_requisicoes,
        }
        return JsonResponse(data)
    except:
        return JsonResponse({'error': 'Cliente não encontrado'}, status=404)