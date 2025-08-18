from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
import string, random

class Funcionario(models.Model):
    nome = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    contacto = models.CharField(max_length=20, blank=True, null=True)
    morada = models.TextField(blank=True, null=True)
    activo = models.BooleanField(default=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

class Cliente(models.Model):
    nome = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    contacto = models.CharField(max_length=20, blank=True, null=True)
    endereco = models.TextField(blank=True, null=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

class Requisicao(models.Model):
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
    requisicao = models.ForeignKey(Requisicao, on_delete=models.CASCADE, related_name='lista_senhas')
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='senhas')
    usada = models.BooleanField(default=False)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.codigo} ({'Usada' if self.usada else 'Disponível'})"

    @staticmethod
    def gerar_codigo(tamanho=10):
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choices(chars, k=tamanho))