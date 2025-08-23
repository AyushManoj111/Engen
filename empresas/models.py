from django.db import models
from django.contrib.auth.models import User

class Empresa(models.Model):
   nome = models.CharField(max_length=200)
   status = models.BooleanField(default=True)
   gerente = models.OneToOneField(User, on_delete=models.CASCADE, related_name='empresa_gerenciada')
   
   def __str__(self):
       return self.nome