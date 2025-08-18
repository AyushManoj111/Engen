from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from gerente.models import Senha
from django.contrib.auth.decorators import user_passes_test


# Create your views here.
def is_funcionario(user):
   """Verifica se o usuário é funcionário"""
   return user.groups.filter(name='Funcionarios').exists()

def login_funcionario_view(request):
    """View para login de funcionários"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None and user.groups.filter(name='Funcionarios').exists():
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
    View para scan de senha e listagem de todas as senhas
    """
    # Buscar todas as senhas ordenadas por data de criação (mais recentes primeiro)
    senhas = Senha.objects.select_related('cliente', 'requisicao').order_by('-data_criacao')
    
    # Calcular estatísticas
    total_senhas = senhas.count()
    senhas_usadas = senhas.filter(usada=True).count()
    senhas_disponiveis = total_senhas - senhas_usadas
    
    # Processar formulário de scan
    if request.method == 'POST':
        codigo_senha = request.POST.get('senha', '').strip()
        
        if codigo_senha:
            try:
                # Buscar a senha pelo código
                senha = Senha.objects.get(codigo=codigo_senha)
                
                if senha.usada:
                    messages.error(request, f'Senha {codigo_senha} já foi utilizada!')
                else:
                    # Marcar como usada
                    senha.usada = True
                    senha.save()
                    messages.success(request, f'Senha {codigo_senha} escaneada com sucesso!')
                    
                    # Redirecionar para evitar resubmissão do formulário
                    return redirect('scan_senha')  # Nome da URL
                    
            except Senha.DoesNotExist:
                messages.error(request, f'Senha {codigo_senha} não encontrada!')
        else:
            messages.error(request, 'Por favor, digite uma senha válida!')
    
    context = {
        'senhas': senhas,
        'total_senhas': total_senhas,
        'senhas_usadas': senhas_usadas,
        'senhas_disponiveis': senhas_disponiveis,
    }
    
    return render(request, 'funcionario/dashboard_funcionario.html', context)

"""
def listar_senhas_view(request):
    
    # Filtros opcionais
    status = request.GET.get('status')  # 'usada', 'disponivel'
    cliente_id = request.GET.get('cliente')
    busca = request.GET.get('busca')
    
    # Query base
    senhas = Senha.objects.select_related('cliente', 'requisicao')
    
    # Aplicar filtros
    if status == 'usada':
        senhas = senhas.filter(usada=True)
    elif status == 'disponivel':
        senhas = senhas.filter(usada=False)
    
    if cliente_id:
        senhas = senhas.filter(cliente_id=cliente_id)
    
    if busca:
        senhas = senhas.filter(
            Q(codigo__icontains=busca) |
            Q(cliente__nome__icontains=busca)
        )
    
    # Ordenar por data de criação
    senhas = senhas.order_by('-data_criacao')
    
    # Calcular estatísticas
    total_senhas = senhas.count()
    senhas_usadas = senhas.filter(usada=True).count()
    senhas_disponiveis = total_senhas - senhas_usadas
    
    context = {
        'senhas': senhas,
        'total_senhas': total_senhas,
        'senhas_usadas': senhas_usadas,
        'senhas_disponiveis': senhas_disponiveis,
    }
    
    return render(request, 'funcionario/dashboard_funcionario.html', context)
"""