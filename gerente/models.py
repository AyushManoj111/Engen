from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
import string, random
from django.contrib.auth.models import User

class Funcionario(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)  # Ligação com User
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
    nome = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    contacto = models.CharField(max_length=20, blank=True, null=True)
    endereco = models.TextField(blank=True, null=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

class RequisicaoSenhas(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='requisicoes')
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    senhas = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    funcionario_responsavel = models.ForeignKey(Funcionario, on_delete=models.SET_NULL, null=True, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_conclusao = models.DateTimeField(null=True, blank=True)
    ativa = models.BooleanField(default=True)

    def __str__(self):
        return f"Requisição #{self.id} - {self.cliente.nome}"

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


class Senha(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    requisicao = models.ForeignKey(RequisicaoSenhas, on_delete=models.CASCADE, related_name='lista_senhas')
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='senhas')
    usada = models.BooleanField(default=False)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.codigo} ({'Usada' if self.usada else 'Disponível'})"

    @staticmethod
    def gerar_codigo(tamanho=10):
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choices(chars, k=tamanho))
    

def gerar_codigo():
    """Gera um código aleatório de 10 caracteres alfanuméricos"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

class RequisicaoSaldo(models.Model):
    cliente = models.ForeignKey("Cliente", on_delete=models.CASCADE, related_name='requisicoes_saldo')
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    funcionario_responsavel = models.ForeignKey("Funcionario", on_delete=models.SET_NULL, null=True, blank=True)
    codigo = models.CharField(max_length=10, unique=True, default=gerar_codigo, editable=False)
    data_criacao = models.DateTimeField(auto_now_add=True)
    ativa = models.BooleanField(default=True)

    def __str__(self):
        return f"Saldo #{self.id} ({self.codigo}) - {self.cliente.nome}"

    @property
    def saldo_restante(self):
        total_debitos = self.movimentos.aggregate(models.Sum("valor"))["valor__sum"] or 0
        return self.valor_total - total_debitos
    
class Movimento(models.Model):
    requisicao_saldo = models.ForeignKey('RequisicaoSaldo', on_delete=models.CASCADE, related_name='movimentos')
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    descricao = models.CharField(max_length=200, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Movimento {self.valor} - {self.requisicao_saldo.codigo}"