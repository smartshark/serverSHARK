from django.conf.urls import url


from . import views

urlpatterns = [
    url(r'^collection/start/$', views.collection_start, name='collection'),
    url(r'^collection/arguments/$', views.collection_arguments, name='collection_arguments'),
    url(r'^install/$', views.install, name='install')
]