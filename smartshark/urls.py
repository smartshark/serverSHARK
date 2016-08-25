from django.conf.urls import url
from django.core.urlresolvers import reverse_lazy
from django.contrib.auth.views import login, logout
from . import views

urlpatterns = [
    url(r'^login/$', login, name='mysite_login'),
    url(r'^logout/$', logout, {'next_page': reverse_lazy('index')}, name='mysite_logout'),
    url(r'^$', views.index, name='index'),
    url(r'^spark/submit/$', views.spark_submit, name='spark_submit'),
    url(r'^project/collection/start/$', views.collection_start, name='collection'),
    url(r'^project/collection/arguments/$', views.collection_arguments, name='collection_arguments'),
    url(r'^project/plugin_status/(?P<id>[0-9]+)$', views.plugin_status, name='plugin_status'),
    url(r'^project/plugin_execution/(?P<id>[0-9]+)/$', views.plugin_execution_status, name='plugin_execution_status'),
    url(r'^project/job/(?P<id>[0-9]+)/(?P<type>[a-z]+)$', views.job_output, name='job_output'),
    url(r'^plugin/install/$', views.install, name='install')
]