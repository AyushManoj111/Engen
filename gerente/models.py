from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.utils import timezone
import string, random

class Funcionario(models.Model):
    """
    Model para funcionários do sistema ENGEN
    """
    nome = models.CharField(max_length=100, verbose_name="Nome")
    email = models.EmailField(unique=True, verbose_name="Email")
    password = models.CharField(max_length=128, null=True, blank=True)
    contacto = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        verbose_name="Contacto",
        help_text="Ex: +258 XX XXX XXXX"
    )
    morada = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Morada",
        help_text="Endereço completo"
    )
    data_criacao = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Data de Criação"
    )
    data_atualizacao = models.DateTimeField(
        auto_now=True, 
        verbose_name="Última Atualização"
    )
    ativo = models.BooleanField(
        default=True, 
        verbose_name="Ativo",
        help_text="Funcionário ativo no sistema"
    )

    class Meta:
        verbose_name = "Funcionário"
        verbose_name_plural = "Funcionários"
        ordering = ['-data_criacao']

    def __str__(self):
        return f"{self.nome} ({self.email})"

    def save(self, *args, **kwargs):
        # Garantir que o email seja sempre minúsculo
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)


class Cliente(models.Model):
    """
    Model para clientes do sistema ENGEN
    """
    nome = models.CharField(max_length=100, verbose_name="Nome")
    contacto = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        verbose_name="Contacto",
        help_text="Ex: +258 XX XXX XXXX"
    )
    endereco = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Endereço",
        help_text="Endereço completo do cliente"
    )
    email = models.EmailField(
        blank=True, 
        null=True, 
        verbose_name="Email"
    )
    data_criacao = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Data de Criação"
    )
    data_atualizacao = models.DateTimeField(
        auto_now=True, 
        verbose_name="Última Atualização"
    )
    ativo = models.BooleanField(
        default=True, 
        verbose_name="Ativo",
        help_text="Cliente ativo no sistema"
    )

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ['-data_criacao']

    def __str__(self):
        return self.nome

    @property
    def total_requisicoes(self):
        """Retorna o total de requisições do cliente"""
        return self.requisicoes.count()

    @property
    def valor_total_requisicoes(self):
        """Retorna o valor total de todas as requisições do cliente"""
        return self.requisicoes.aggregate(
            total=models.Sum('valor')
        )['total'] or 0

    def save(self, *args, **kwargs):
        # Garantir que o email seja sempre minúsculo se fornecido
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)


class Requisicao(models.Model):
    """
    Model para requisições do sistema ENGEN
    """
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='requisicoes',
        verbose_name="Cliente"
    )
    valor = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Valor (MT)",
        help_text="Valor em Meticais"
    )
    senhas = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Quantidade de Senhas",
        help_text="Quantidade total de senhas para esta requisição"
    )
    senhas_restantes = models.PositiveIntegerField(
        verbose_name="Senhas Restantes",
        help_text="Quantidade de senhas ainda disponíveis"
    )
    observacoes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observações",
        help_text="Observações adicionais sobre a requisição"
    )
    funcionario_responsavel = models.ForeignKey(
        Funcionario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requisicoes_responsavel',
        verbose_name="Funcionário Responsável"
    )
    data_criacao = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Data de Criação"
    )
    data_atualizacao = models.DateTimeField(
        auto_now=True,
        verbose_name="Última Atualização"
    )
    data_conclusao = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data de Conclusão"
    )
    ativa = models.BooleanField(
        default=True,
        verbose_name="Ativa",
        help_text="Requisição ativa no sistema"
    )

    class Meta:
        verbose_name = "Requisição"
        verbose_name_plural = "Requisições"
        ordering = ['-data_criacao']

    def __str__(self):
        return f"Requisição #{self.id} - {self.cliente.nome}"

    def save(self, *args, **kwargs):
        # Se é uma nova requisição, senhas_restantes = senhas
        if not self.pk and not self.senhas_restantes:
            self.senhas_restantes = self.senhas
        
        # Marcar como concluída se senhas_restantes = 0
        if self.senhas_restantes == 0 and not self.data_conclusao:
            self.data_conclusao = timezone.now()
        elif self.senhas_restantes > 0 and self.data_conclusao:
            self.data_conclusao = None
            
        super().save(*args, **kwargs)

    @property
    def status(self):
        """Retorna o status baseado nas senhas restantes"""
        if self.senhas_restantes == 0:
            return 'completo'
        elif self.senhas_restantes <= 5:
            return 'baixo'
        elif self.senhas_restantes <= 15:
            return 'medio'
        else:
            return 'alto'

    @property
    def status_display(self):
        """Retorna o status em texto legível"""
        status_map = {
            'completo': 'Concluída',
            'baixo': 'Poucas Senhas',
            'medio': 'Em Andamento',
            'alto': 'Disponível'
        }
        return status_map.get(self.status, 'Desconhecido')

    @property
    def porcentagem_utilizada(self):
        """Retorna a porcentagem de senhas utilizadas"""
        if self.senhas == 0:
            return 0
        return ((self.senhas - self.senhas_restantes) / self.senhas) * 100

    @property
    def senhas_utilizadas(self):
        """Retorna a quantidade de senhas já utilizadas"""
        return self.senhas - self.senhas_restantes

    def diminuir_senha(self, quantidade=1):
        """Método para diminuir senhas restantes"""
        if self.senhas_restantes >= quantidade:
            self.senhas_restantes -= quantidade
            self.save()
            return True
        return False

    def adicionar_senha(self, quantidade=1):
        """Método para adicionar senhas (até o limite total)"""
        if self.senhas_restantes + quantidade <= self.senhas:
            self.senhas_restantes += quantidade
            self.save()
            return True
        return False

class Senha(models.Model):
    """
    Senhas geradas automaticamente para cada requisição
    """
    codigo = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Código da Senha"
    )
    requisicao = models.ForeignKey(
        'Requisicao',
        on_delete=models.CASCADE,
        related_name='lista_senhas'
    )
    cliente = models.ForeignKey(
        'Cliente',
        on_delete=models.CASCADE,
        related_name='senhas'
    )
    usada = models.BooleanField(default=False)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.codigo} ({'Usada' if self.usada else 'Disponível'})"

    @staticmethod
    def gerar_codigo(tamanho=10):
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choices(chars, k=tamanho))

class HistoricoSenha(models.Model):
    """
    Model para registrar o histórico de uso de senhas
    """
    requisicao = models.ForeignKey(
        Requisicao,
        on_delete=models.CASCADE,
        related_name='historico_senhas',
        verbose_name="Requisição"
    )
    quantidade = models.IntegerField(
        verbose_name="Quantidade",
        help_text="Quantidade de senhas (positivo = adicionado, negativo = usado)"
    )
    motivo = models.CharField(
        max_length=200,
        verbose_name="Motivo",
        help_text="Motivo da alteração"
    )
    funcionario = models.ForeignKey(
        Funcionario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Funcionário"
    )
    data_criacao = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Data"
    )

    class Meta:
        verbose_name = "Histórico de Senha"
        verbose_name_plural = "Histórico de Senhas"
        ordering = ['-data_criacao']

    def __str__(self):
        operacao = "Adicionou" if self.quantidade > 0 else "Usou"
        return f"{operacao} {abs(self.quantidade)} senha(s) - Req #{self.requisicao.id}"

# Model adicional para configurações do sistema (opcional)
class ConfiguracaoSistema(models.Model):
    """
    Model para configurações gerais do sistema
    """
    nome_empresa = models.CharField(
        max_length=100,
        default="ENGEN",
        verbose_name="Nome da Empresa"
    )
    limite_senhas_aviso = models.PositiveIntegerField(
        default=5,
        verbose_name="Limite para Aviso de Senhas",
        help_text="Quantidade mínima que gera aviso de poucas senhas"
    )
    moeda = models.CharField(
        max_length=10,
        default="MT",
        verbose_name="Moeda"
    )
    data_atualizacao = models.DateTimeField(
        auto_now=True,
        verbose_name="Última Atualização"
    )

    class Meta:
        verbose_name = "Configuração do Sistema"
        verbose_name_plural = "Configurações do Sistema"

    def __str__(self):
        return f"Configurações - {self.nome_empresa}"