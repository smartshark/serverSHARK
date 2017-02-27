from django.conf.urls import url
from django.core.urlresolvers import reverse_lazy
from django.contrib.auth.views import login, logout

from smartshark.views import analysis, common, collection

urlpatterns = [
    # Frontend
    url(r'^login/$', login, name='mysite_login'),
    url(r'^logout/$', logout, {'next_page': reverse_lazy('index')}, name='mysite_logout'),
    url(r'^$', common.index, name='index'),
    url(r'^documentation/$', common.documentation, name='documentation'),
    url(r'^spark/submit/$', analysis.spark_submit, name='spark_submit'),

    # Backend
    url(r'^smartshark/project/collection/choose/$', collection.choose_plugins, name='choose_plugins'),
    url(r'^smartshark/project/collection/start/$', collection.start_collection, name='collection_start'),
    url(r'^smartshark/project/plugin_status/(?P<id>[0-9]+)$', common.plugin_status, name='plugin_status'),
    url(r'^smartshark/project/plugin_execution/(?P<id>[0-9]+)/$', common.plugin_execution_status, name='plugin_execution_status'),
    url(r'^smartshark/project/job/(?P<id>[0-9]+)/(?P<type>[a-z]+)$', common.job_output, name='job_output'),
    url(r'^smartshark/plugin/install/$', collection.install, name='install')
]