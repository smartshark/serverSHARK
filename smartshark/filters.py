import django_filters
from .models import Job

class JobExecutionFilter(django_filters.FilterSet):
    class Meta:
        model = Job
        fields = ['status', 'revision_hash']