from .models import Plugin
from django import forms


class ProjectForm(forms.Form):
    plugins = forms.ModelMultipleChoiceField(queryset=Plugin.objects.all().filter(active=True, installed=True))