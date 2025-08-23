from django.shortcuts import render, redirect
from django.contrib.auth.models import User, Group
from django.contrib import messages
from .models import Empresa

def criar_empresa(request):
    if request.method == 'POST':
        nome = request.POST['nome']
        status = request.POST.get('status') == 'on'
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        
        # Criar usuário gerente
        gerente = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        
        # Adicionar ao grupo gerente
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        gerente.groups.add(grupo_gerente)
        
        # Criar empresa
        Empresa.objects.create(
            nome=nome,
            status=status,
            gerente=gerente
        )
        
        messages.success(request, 'Empresa criada com sucesso!')
        return redirect('criar_empresa')
    
    return render(request, 'empresas/criar_empresa.html')