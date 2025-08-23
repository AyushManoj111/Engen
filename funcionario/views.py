from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from gerente.models import Senha, RequisicaoSaldo, Movimento, Funcionario
from django.contrib.auth.decorators import user_passes_test
from decimal import Decimal


# Create your views here.
def is_funcionario(user):
    """Verifica se o usuário é funcionário"""
    return user.groups.filter(name='Funcionarios').exists()


def get_empresa_funcionario(user):
    """Retorna a empresa do funcionário logado"""
    try:
        if hasattr(user, 'funcionario'):
            return user.funcionario.empresa
        # Fallback: tentar buscar pelo relacionamento inverso
        funcionario = Funcionario.objects.filter(user=user, activo=True).first()
        if funcionario:
            return funcionario.empresa
    except:
        pass
    return None


def login_funcionario_view(request):
    """View para login de funcionários"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None and user.groups.filter(name='Funcionarios').exists():
            # Verificar se o funcionário está ativo e tem empresa
            empresa = get_empresa_funcionario(user)
            if not empresa:
                messages.error(request, 'Funcionário não está associado a nenhuma empresa ou está inativo.')
                return render(request, 'funcionario/login_funcionario.html')
            
            login(request, user)
            return redirect('funcionariodashboard')
        else:
            messages.error(request, 'Apenas funcionários podem acessar este login.')
    
    return render(request, 'funcionario/login_funcionario.html')


def logout_view(request):
    """View para logout"""
    logout(request)
    messages.success(request, 'Você foi desconectado com sucesso')
    return redirect('')


@user_passes_test(is_funcionario, login_url='/login/')
def scan_senha_view(request):
    """
    View para scan de senha e débito de saldo - APENAS da empresa do funcionário
    """
    # CRÍTICO: Obter empresa do funcionário logado
    empresa = get_empresa_funcionario(request.user)
    if not empresa:
        messages.error(request, 'Funcionário não está associado a nenhuma empresa.')
        return redirect('login_funcionario')
    
    # Buscar apenas senhas DA EMPRESA do funcionário
    senhas = (
        Senha.objects
        .select_related('cliente', 'requisicao')
        .filter(empresa=empresa)  # FILTRO CRÍTICO
        .order_by('-data_criacao')
    )
    
    # Calcular estatísticas APENAS da empresa
    total_senhas = senhas.count()
    senhas_usadas = senhas.filter(usada=True).count()
    senhas_disponiveis = total_senhas - senhas_usadas
    
    # Processar formulário de scan
    if request.method == 'POST':
        codigo_string = request.POST.get('string', '').strip()
        valor = request.POST.get('valor', '').strip()
        
        if codigo_string:
            # Verificar se é senha ou código de requisição de saldo DA EMPRESA
            senha_encontrada = None
            requisicao_saldo_encontrada = None
            
            # Primeiro, tentar encontrar como senha DA EMPRESA
            try:
                senha_encontrada = Senha.objects.get(
                    codigo=codigo_string,
                    empresa=empresa  # FILTRO CRÍTICO
                )
            except Senha.DoesNotExist:
                pass
            
            # Depois, tentar encontrar como código de requisição de saldo DA EMPRESA
            try:
                requisicao_saldo_encontrada = RequisicaoSaldo.objects.get(
                    codigo=codigo_string,
                    empresa=empresa,  # FILTRO CRÍTICO
                    ativa=True
                )
            except RequisicaoSaldo.DoesNotExist:
                pass
            
            # Processar senha
            if senha_encontrada:
                if not valor:  # Sem valor = marcar senha como usada
                    if senha_encontrada.usada:
                        messages.error(request, f'Senha {codigo_string} já foi utilizada!')
                    else:
                        senha_encontrada.usada = True
                        senha_encontrada.data_uso = timezone.now()  # Registrar quando foi usada
                        senha_encontrada.funcionario_uso = request.user.funcionario if hasattr(request.user, 'funcionario') else None  # Quem escaneou
                        senha_encontrada.save()
                        messages.success(request, f'Senha {codigo_string} escaneada com sucesso!')
                else:
                    messages.error(request, f'Senhas não precisam de valor. Use apenas o código.')
                    
            # Processar requisição de saldo
            elif requisicao_saldo_encontrada:
                if valor:  # Com valor = debitar do saldo
                    try:
                        valor_decimal = Decimal(valor)
                        if valor_decimal <= 0:
                            messages.error(request, 'Valor deve ser maior que zero!')
                        elif valor_decimal > requisicao_saldo_encontrada.saldo_restante:
                            messages.error(request, f'Saldo insuficiente! Disponível: {requisicao_saldo_encontrada.saldo_restante} MT')
                        else:
                            # Criar movimento de débito
                            movimento = Movimento.objects.create(
                                requisicao_saldo=requisicao_saldo_encontrada,
                                valor=valor_decimal,
                                descricao=f'Débito via scan - Funcionário: {request.user.get_full_name() or request.user.username}',
                                funcionario=request.user.funcionario if hasattr(request.user, 'funcionario') else None  # Rastrear quem fez
                            )
                            messages.success(request, f'Débito de {valor_decimal} MT realizado com sucesso!')
                    except (ValueError, TypeError):
                        messages.error(request, 'Valor inválido!')
                else:
                    messages.error(request, f'Para débito de saldo é necessário informar o valor.')
            
            else:
                messages.error(request, f'Código {codigo_string} não encontrado ou não pertence à sua empresa!')
                
        else:
            messages.error(request, 'Por favor, digite um código válido!')
            
        # Redirecionar para evitar resubmissão do formulário
        return redirect('scan_senha')
    
    context = {
        'senhas': senhas[:50],  # Limitar para performance
        'total_senhas': total_senhas,
        'senhas_usadas': senhas_usadas,
        'senhas_disponiveis': senhas_disponiveis,
        'empresa': empresa,  # Para mostrar no template
        'funcionario': request.user.funcionario if hasattr(request.user, 'funcionario') else None,
    }
    
    return render(request, 'funcionario/dashboard_funcionario.html', context)


@user_passes_test(is_funcionario, login_url='/login/')
def funcionario_dashboard(request):
    """
    Dashboard específico para funcionários com estatísticas da empresa
    """
    empresa = get_empresa_funcionario(request.user)
    if not empresa:
        messages.error(request, 'Funcionário não está associado a nenhuma empresa.')
        return redirect('login_funcionario')
    
    # Estatísticas básicas DA EMPRESA
    stats = {
        'senhas_ativas': Senha.objects.filter(empresa=empresa, usada=False).count(),
        'senhas_usadas_hoje': Senha.objects.filter(
            empresa=empresa,
            usada=True,
            data_uso__date=timezone.now().date()
        ).count() if hasattr(Senha, 'data_uso') else 0,
        'requisicoes_saldo_ativas': RequisicaoSaldo.objects.filter(
            empresa=empresa,
            ativa=True
        ).count(),
    }
    
    # Últimas senhas escaneadas (se existir campo data_uso)
    ultimas_senhas = (
        Senha.objects
        .filter(empresa=empresa, usada=True)
        .select_related('cliente', 'requisicao')
        .order_by('-data_criacao')[:10]
    )
    
    context = {
        'empresa': empresa,
        'funcionario': request.user.funcionario if hasattr(request.user, 'funcionario') else None,
        'stats': stats,
        'ultimas_senhas': ultimas_senhas,
    }
    
    return render(request, 'funcionario/dashboard.html', context)