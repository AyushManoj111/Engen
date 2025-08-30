from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from gerente.models import Senha, RequisicaoSaldo, Movimento, Funcionario
from django.contrib.auth.decorators import user_passes_test, login_required
from decimal import Decimal
import cv2
import json
import base64
import numpy as np
from pyzbar import pyzbar
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
import threading
import time


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


@login_required(login_url='/funcionario/login')
@user_passes_test(is_funcionario, login_url='/login')
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
        tipo_combustivel = request.POST.get('tipo_combustivel', '').strip()
        
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
                        senha_encontrada.data_uso = timezone.now()
                        senha_encontrada.funcionario_uso = request.user.funcionario if hasattr(request.user, 'funcionario') else None
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
                            # Validar tipo de combustível para débitos
                            if not tipo_combustivel or tipo_combustivel not in ['gasolina', 'diesel']:
                                messages.error(request, 'Por favor, selecione o tipo de combustível (Gasolina ou Diesel).')
                            else:
                                # Criar movimento de débito com tipo de combustível
                                movimento = Movimento.objects.create(
                                    requisicao_saldo=requisicao_saldo_encontrada,
                                    valor=valor_decimal,
                                    tipo_combustivel=tipo_combustivel,
                                    descricao=f'Débito via scan ({tipo_combustivel.title()}) - Funcionário: {request.user.get_full_name() or request.user.username}',
                                    funcionario=request.user.funcionario if hasattr(request.user, 'funcionario') else None
                                )
                                
                                messages.success(request, 
                                    f'Débito de {valor_decimal} MT realizado com sucesso! '
                                    f'Combustível: {tipo_combustivel.title()}'
                                )
                    except (ValueError, TypeError):
                        messages.error(request, 'Valor inválido!')
                else:
                    messages.error(request, f'Para débito de saldo é necessário informar o valor e tipo de combustível.')
            
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
        'empresa': empresa,
        'funcionario': request.user.funcionario if hasattr(request.user, 'funcionario') else None,
    }
    
    return render(request, 'funcionario/dashboard_funcionario.html', context)


@login_required(login_url='/funcionario/login')
@user_passes_test(is_funcionario, login_url='/login')
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

# Variável global para controlar o estado da câmera
camera_active = {}

@login_required(login_url='/funcionario/login')
@user_passes_test(is_funcionario, login_url='/login')
def generate_camera_frames(camera_id=0):
    """
    Gerador de frames da câmera para streaming
    """
    cap = cv2.VideoCapture(camera_id)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    try:
        while camera_active.get(camera_id, False):
            success, frame = cap.read()
            if not success:
                break
            
            # Detectar QR codes
            qr_codes = pyzbar.decode(frame)
            
            # Desenhar retângulos ao redor dos QR codes detectados
            for qr_code in qr_codes:
                # Extrair posição do QR code
                (x, y, w, h) = qr_code.rect
                
                # Desenhar retângulo verde ao redor do QR code
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                
                # Decodificar dados do QR code
                qr_data = qr_code.data.decode('utf-8')
                
                # Adicionar texto com o código detectado
                cv2.putText(frame, qr_data, (x, y - 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
            # Converter frame para JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            
            # Retornar frame em formato de streaming
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            time.sleep(0.1)  # Pequeno delay para controlar FPS
    finally:
        cap.release()

@login_required(login_url='/funcionario/login')
@user_passes_test(is_funcionario, login_url='/login')
def camera_stream(request):
    """
    View para streaming da câmera
    """
    camera_id = 0
    camera_active[camera_id] = True
    
    response = StreamingHttpResponse(
        generate_camera_frames(camera_id),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    
    return response

@csrf_exempt
@require_http_methods(["POST"])
@login_required(login_url='/funcionario/login')
@user_passes_test(is_funcionario, login_url='/login')
def stop_camera(request):
    """
    View para parar a câmera
    """
    camera_id = 0
    camera_active[camera_id] = False
    return JsonResponse({'status': 'stopped'})

@csrf_exempt
@require_http_methods(["POST"])
@login_required(login_url='/funcionario/login')
@user_passes_test(is_funcionario, login_url='/login')
def scan_qr_code(request):
    """
    View para processar imagem e detectar QR codes
    """
    try:
        # Obter empresa do funcionário
        empresa = get_empresa_funcionario(request.user)
        if not empresa:
            return JsonResponse({
                'success': False, 
                'error': 'Funcionário não está associado a nenhuma empresa.'
            })
        
        # Obter dados da requisição
        data = json.loads(request.body)
        image_data = data.get('image')
        
        if not image_data:
            return JsonResponse({'success': False, 'error': 'Nenhuma imagem fornecida'})
        
        # Decodificar imagem base64
        image_data = image_data.split(',')[1]  # Remover prefixo data:image/jpeg;base64,
        image_bytes = base64.b64decode(image_data)
        
        # Converter para numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Detectar QR codes
        qr_codes = pyzbar.decode(frame)
        
        if not qr_codes:
            return JsonResponse({'success': False, 'error': 'Nenhum QR code detectado'})
        
        # Processar primeiro QR code encontrado
        qr_code = qr_codes[0]
        codigo_string = qr_code.data.decode('utf-8').strip()
        
        # Buscar senha ou requisição de saldo
        senha_encontrada = None
        requisicao_saldo_encontrada = None
        
        # Tentar encontrar como senha DA EMPRESA
        try:
            senha_encontrada = Senha.objects.get(
                codigo=codigo_string,
                empresa=empresa
            )
        except Senha.DoesNotExist:
            pass
        
        # Tentar encontrar como código de requisição de saldo DA EMPRESA
        try:
            requisicao_saldo_encontrada = RequisicaoSaldo.objects.get(
                codigo=codigo_string,
                empresa=empresa,
                ativa=True
            )
        except RequisicaoSaldo.DoesNotExist:
            pass
        
        if senha_encontrada:
            return JsonResponse({
                'success': True,
                'type': 'senha',
                'codigo': codigo_string,
                'data': {
                    'usada': senha_encontrada.usada,
                    'cliente': senha_encontrada.cliente.nome if senha_encontrada.cliente else 'N/A',
                    'data_criacao': senha_encontrada.data_criacao.strftime('%d/%m/%Y %H:%M'),
                }
            })
        elif requisicao_saldo_encontrada:
            return JsonResponse({
                'success': True,
                'type': 'saldo',
                'codigo': codigo_string,
                'data': {
                    'saldo_restante': float(requisicao_saldo_encontrada.saldo_restante),
                    'cliente': requisicao_saldo_encontrada.cliente.nome if requisicao_saldo_encontrada.cliente else 'N/A',
                    'data_criacao': requisicao_saldo_encontrada.data_criacao.strftime('%d/%m/%Y %H:%M'),
                }
            })
        else:
            return JsonResponse({
                'success': False, 
                'error': f'Código {codigo_string} não encontrado ou não pertence à sua empresa!'
            })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Erro ao processar: {str(e)}'})

@csrf_exempt
@require_http_methods(["POST"])
@login_required(login_url='/funcionario/login')
@user_passes_test(is_funcionario, login_url='/login')
def process_scanned_code(request):
    """
    View para processar código escaneado (marcar senha como usada ou debitar saldo)
    """
    try:
        empresa = get_empresa_funcionario(request.user)
        if not empresa:
            return JsonResponse({
                'success': False, 
                'error': 'Funcionário não está associado a nenhuma empresa.'
            })
        
        data = json.loads(request.body)
        codigo_string = data.get('codigo', '').strip()
        valor = data.get('valor', '')
        tipo_combustivel = data.get('tipo_combustivel', '')
        tipo = data.get('type', '')  # 'senha' ou 'saldo'
        
        if not codigo_string:
            return JsonResponse({'success': False, 'error': 'Código não fornecido'})
        
        if tipo == 'senha':
            # Processar senha
            try:
                senha = Senha.objects.get(codigo=codigo_string, empresa=empresa)
                if senha.usada:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Senha {codigo_string} já foi utilizada!'
                    })
                else:
                    senha.usada = True
                    senha.data_uso = timezone.now()
                    senha.funcionario_uso = request.user.funcionario if hasattr(request.user, 'funcionario') else None
                    senha.save()
                    return JsonResponse({
                        'success': True, 
                        'message': f'Senha {codigo_string} escaneada com sucesso!'
                    })
            except Senha.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Senha não encontrada'})
        
        elif tipo == 'saldo':
            # Processar requisição de saldo
            if not valor:
                return JsonResponse({
                    'success': False, 
                    'error': 'Para débito de saldo é necessário informar o valor.'
                })
            
            if not tipo_combustivel or tipo_combustivel not in ['gasolina', 'diesel']:
                return JsonResponse({
                    'success': False, 
                    'error': 'Por favor, selecione o tipo de combustível.'
                })
            
            try:
                requisicao_saldo = RequisicaoSaldo.objects.get(
                    codigo=codigo_string, 
                    empresa=empresa, 
                    ativa=True
                )
                
                valor_decimal = Decimal(valor)
                if valor_decimal <= 0:
                    return JsonResponse({'success': False, 'error': 'Valor deve ser maior que zero!'})
                
                if valor_decimal > requisicao_saldo.saldo_restante:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Saldo insuficiente! Disponível: {requisicao_saldo.saldo_restante} MT'
                    })
                
                # Criar movimento de débito
                movimento = Movimento.objects.create(
                    requisicao_saldo=requisicao_saldo,
                    valor=valor_decimal,
                    tipo_combustivel=tipo_combustivel,
                    descricao=f'Débito via scan QR ({tipo_combustivel.title()}) - Funcionário: {request.user.get_full_name() or request.user.username}',
                    funcionario=request.user.funcionario if hasattr(request.user, 'funcionario') else None
                )
                
                return JsonResponse({
                    'success': True, 
                    'message': f'Débito de {valor_decimal} MT realizado com sucesso! Combustível: {tipo_combustivel.title()}'
                })
                
            except RequisicaoSaldo.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Requisição de saldo não encontrada'})
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Valor inválido!'})
        
        else:
            return JsonResponse({'success': False, 'error': 'Tipo de código inválido'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Erro ao processar: {str(e)}'})