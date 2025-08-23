def empresa_context(request):
    """Context processor para adicionar empresa em todos os templates"""
    if request.user.is_authenticated:
        try:
            # Para gerentes
            if hasattr(request.user, 'empresa_gerenciada'):
                return {'empresa_atual': request.user.empresa_gerenciada}
            # Para funcionários
            elif hasattr(request.user, 'funcionario'):
                return {'empresa_atual': request.user.funcionario.empresa}
        except:
            pass
    return {'empresa_atual': None}