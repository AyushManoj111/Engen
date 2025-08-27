from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
import string, random
from django.contrib.auth.models import User
from empresas.models import Empresa
from decimal import Decimal

class Fecho(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='fechos', null=True, blank=True)
    data = models.DateTimeField(default=timezone.now)
    
    class Meta:
        verbose_name = "Fecho"
        verbose_name_plural = "Fechos"
        ordering = ['-data']
    
    def __str__(self):
        return f"Fecho #{self.id} - {self.data.strftime('%d/%m/%Y %H:%M')}"

class Funcionario(models.Model):
   user = models.OneToOneField(User, on_delete=models.CASCADE)
   empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='funcionarios', null=True, blank=True)
   contacto = models.CharField(max_length=20, blank=True, null=True)
   morada = models.TextField(blank=True, null=True)
   activo = models.BooleanField(default=True)
   data_criacao = models.DateTimeField(auto_now_add=True)

   def __str__(self):
       return self.user.first_name or self.user.username
   
   @property
   def nome(self):
       return self.user.first_name or self.user.username
   
   @property
   def email(self):
       return self.user.email

class Cliente(models.Model):
   empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='clientes', null=True, blank=True)
   nome = models.CharField(max_length=100)
   email = models.EmailField(blank=True, null=True)
   contacto = models.CharField(max_length=20, blank=True, null=True)
   endereco = models.TextField(blank=True, null=True)
   data_criacao = models.DateTimeField(auto_now_add=True)

   def __str__(self):
       return self.nome

class RequisicaoSenhas(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='requisicoes_senhas', null=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='requisicoes')
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    senhas = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    funcionario_responsavel = models.ForeignKey(Funcionario, on_delete=models.SET_NULL, null=True, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_conclusao = models.DateTimeField(null=True, blank=True)
    ativa = models.BooleanField(default=True)
    
    # NOVO CAMPO PARA CONTROLAR FECHO
    fecho = models.ForeignKey(Fecho, on_delete=models.SET_NULL, null=True, blank=True, related_name='requisicoes_senhas')
    
    FORMA_PAGAMENTO_CHOICES = [
        ('transferencia', 'Transferência Bancária'),
        ('cash', 'Dinheiro (Cash)'),
        ('pos', 'POS (Cartão)'),
    ]
    forma_pagamento = models.CharField(
        max_length=20,
        choices=FORMA_PAGAMENTO_CHOICES,
        verbose_name="Forma de Pagamento",
        default='cash'
    )
    banco = models.CharField(max_length=100, null=True, blank=True, verbose_name="Nome do Banco")
    banco = models.CharField(max_length=100, null=True, blank=True, verbose_name="Nome do Banco")

    def __str__(self):
       return f"Requisição #{self.id} - {self.cliente.nome}"

    def get_forma_pagamento_display_icon(self):
        """Retorna ícone para forma de pagamento"""
        icons = {
            'transferencia': 'fas fa-university',
            'cash': 'fas fa-money-bill-wave',
            'pos': 'fas fa-credit-card',
        }
        return icons.get(self.forma_pagamento, 'fas fa-money-bill-wave')

    @property
    def senhas_usadas(self):
       return self.lista_senhas.filter(usada=True).count()

    @property
    def senhas_restantes(self):
       return self.senhas - self.senhas_usadas

    def concluir(self):
       """Marca como concluída se não restarem senhas"""
       if self.senhas_restantes == 0 and not self.data_conclusao:
           self.data_conclusao = timezone.now()
           self.save()

    @property
    def pode_editar(self):
        """Retorna True se a requisição pode ser editada (não foi fechada)"""
        return self.fecho is None
    
    @property
    def pode_excluir(self):
        """Retorna True se a requisição pode ser excluída (não foi fechada)"""
        return self.fecho is None
    
    @property
    def status_fecho(self):
        """Retorna o status do fecho como string"""
        return 'fechado' if self.fecho else 'aberto'
    
    def __str__(self):
        status = " (FECHADA)" if self.fecho else ""
        return f"Requisição #{self.id} - {self.cliente.nome}{status}"

class Senha(models.Model):
    TIPO_COMBUSTIVEL_CHOICES = [
        ('gasolina', 'Gasolina'),
        ('diesel', 'Diesel'),
    ]
    
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='senhas', null=True, blank=True)
    codigo = models.CharField(max_length=20, unique=True)
    requisicao = models.ForeignKey(RequisicaoSenhas, on_delete=models.CASCADE, related_name='lista_senhas')
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='senhas')
    usada = models.BooleanField(default=False)
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_uso = models.DateTimeField(null=True, blank=True)  # Quando foi usada
    funcionario_uso = models.ForeignKey(Funcionario, on_delete=models.SET_NULL, null=True, blank=True, related_name='senhas_escaneadas')  # Quem escaneou
    
    # NOVO CAMPO: Tipo de combustível usado quando a senha foi escaneada
    tipo_combustivel = models.CharField(
        max_length=10, 
        choices=TIPO_COMBUSTIVEL_CHOICES, 
        null=True, 
        blank=True,
        verbose_name="Tipo de Combustível",
        help_text="Tipo de combustível selecionado no momento do uso da senha"
    )
    
    # CAMPO: Fecho individual da senha quando foi usada
    fecho = models.ForeignKey(Fecho, on_delete=models.SET_NULL, null=True, blank=True, related_name='senhas_usadas')
    
    class Meta:
        verbose_name = "Senha"
        verbose_name_plural = "Senhas"
        ordering = ['-data_criacao']
    
    def __str__(self):
        status = 'Usada' if self.usada else 'Disponível'
        fecho_info = f' (Fecho #{self.fecho.id})' if self.fecho else ' (Pendente)' if self.usada else ''
        combustivel_info = f' - {self.get_tipo_combustivel_display()}' if self.tipo_combustivel and self.usada else ''
        return f"{self.codigo} ({status}{combustivel_info}{fecho_info})"

    @staticmethod
    def gerar_codigo(tamanho=10):
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choices(chars, k=tamanho))
    
    @property
    def pode_ser_usada(self):
        """Retorna True se a senha pode ser usada (não usada ainda)"""
        return not self.usada
    
    @property
    def status_fecho(self):
        """Retorna o status do fecho da senha"""
        if not self.usada:
            return 'nao_usada'
        elif self.usada and self.fecho:
            return 'fechada'
        else:
            return 'pendente'
    
    @property
    def status_display(self):
        """Retorna status para display"""
        if not self.usada:
            return 'Disponível'
        elif self.fecho:
            combustivel_info = f' - {self.get_tipo_combustivel_display()}' if self.tipo_combustivel else ''
            return f'Usada (Fechada #{self.fecho.id}{combustivel_info})'
        else:
            combustivel_info = f' - {self.get_tipo_combustivel_display()}' if self.tipo_combustivel else ''
            return f'Usada (Pendente fecho{combustivel_info})'
    
    def usar(self, funcionario, tipo_combustivel=None):
        """Marca senha como usada por um funcionário com tipo de combustível - FICA PENDENTE PARA FECHO"""
        if self.usada:
            raise ValueError("Senha já foi usada")
        
        self.usada = True
        self.data_uso = timezone.now()
        self.funcionario_uso = funcionario
        self.tipo_combustivel = tipo_combustivel  # NOVO: Armazenar tipo de combustível
        self.fecho = None  # Fica pendente até próximo fecho
        self.save()
        
        # Verificar se completou a requisição
        self.requisicao.concluir()
        
        return True

def gerar_codigo():
   """Gera um código aleatório de 10 caracteres alfanuméricos"""
   return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

class RequisicaoSaldo(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='requisicoes_saldo', null=True, blank=True)
    cliente = models.ForeignKey("Cliente", on_delete=models.CASCADE, related_name='requisicoes_saldo')
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    funcionario_responsavel = models.ForeignKey("Funcionario", on_delete=models.SET_NULL, null=True, blank=True)
    codigo = models.CharField(max_length=10, unique=True, default=gerar_codigo, editable=False)
    data_criacao = models.DateTimeField(auto_now_add=True)
    ativa = models.BooleanField(default=True)
    
    # NOVO CAMPO PARA CONTROLAR FECHO
    fecho = models.ForeignKey(Fecho, on_delete=models.SET_NULL, null=True, blank=True, related_name='requisicoes_saldo')
    
    FORMA_PAGAMENTO_CHOICES = [
        ('transferencia', 'Transferência Bancária'),
        ('cash', 'Dinheiro (Cash)'),
        ('pos', 'POS (Cartão)'),
    ]
    
    forma_pagamento = models.CharField(
        max_length=20,
        choices=FORMA_PAGAMENTO_CHOICES,
        verbose_name="Forma de Pagamento",
        default='cash'
    )
    
    banco = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Nome do Banco",
        help_text="Obrigatório apenas para transferência bancária"
    )

    def get_forma_pagamento_display_icon(self):
        """Retorna ícone para forma de pagamento"""
        icons = {
            'transferencia': 'fas fa-university',
            'cash': 'fas fa-money-bill-wave',
            'pos': 'fas fa-credit-card',
        }
        return icons.get(self.forma_pagamento, 'fas fa-money-bill-wave')

    #def __str__(self):
    #    return f"Saldo #{self.id} ({self.codigo}) - {self.cliente.nome}"

    @property
    def saldo_restante(self):
        total_debitos = self.movimentos.aggregate(models.Sum("valor"))["valor__sum"] or 0
        return self.valor_total - total_debitos
    
    @property
    def pode_editar(self):
        """Retorna True se a requisição pode ser editada (não foi fechada)"""
        return self.fecho is None
    
    @property
    def pode_excluir(self):
        """Retorna True se a requisição pode ser excluída (não foi fechada)"""
        return self.fecho is None
    
    @property
    def status_fecho(self):
        """Retorna o status do fecho como string"""
        return 'fechado' if self.fecho else 'aberto'
    
    def __str__(self):
        status = " (FECHADA)" if self.fecho else ""
        return f"Req. Saldo {self.codigo} - {self.cliente.nome}{status}"
   
class Movimento(models.Model):
    TIPO_COMBUSTIVEL_CHOICES = [
        ('gasolina', 'Gasolina'),
        ('diesel', 'Diesel'),
    ]
    
    # REMOVER: empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='movimentos', null=True, blank=True)
    # O relacionamento com empresa deve ser através de requisicao_saldo
    
    requisicao_saldo = models.ForeignKey('RequisicaoSaldo', on_delete=models.CASCADE, related_name='movimentos')
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    tipo_combustivel = models.CharField(max_length=10, choices=TIPO_COMBUSTIVEL_CHOICES, null=True, blank=True)
    descricao = models.CharField(max_length=200, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    funcionario = models.ForeignKey(Funcionario, on_delete=models.SET_NULL, null=True, blank=True, related_name='movimentos_realizados')
    
    # CAMPO PARA CONTROLAR FECHO
    fecho = models.ForeignKey(Fecho, on_delete=models.SET_NULL, null=True, blank=True, related_name='movimentos')
    
    # REMOVER DUPLICAÇÃO:
    # banco = models.CharField(max_length=100, null=True, blank=True, verbose_name="Nome do Banco")
    
    @property
    def empresa(self):
        """Propriedade para acessar a empresa através da requisição de saldo"""
        return self.requisicao_saldo.empresa if self.requisicao_saldo else None
    
    def __str__(self):
        combustivel_info = f" ({self.get_tipo_combustivel_display()})" if self.tipo_combustivel else ""
        return f"Movimento {self.valor} MT{combustivel_info} - {self.requisicao_saldo.codigo}"
    
class LogSistema(models.Model):
    TIPOS_ACAO = [
        ('SENHA_ESCANEADA', 'Senha Escaneada'),
        ('DEBITO_SALDO', 'Débito de Saldo'),
        ('LOGIN', 'Login'),
        ('LOGOUT', 'Logout'),
    ]
    
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='logs')
    funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE, related_name='logs')
    tipo_acao = models.CharField(max_length=20, choices=TIPOS_ACAO)
    descricao = models.TextField()
    data_hora = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        ordering = ['-data_hora']
    
    def __str__(self):
        return f"{self.funcionario.nome} - {self.tipo_acao} - {self.data_hora}"