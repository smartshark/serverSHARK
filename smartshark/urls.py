from django.conf.urls import url


from . import views

urlpatterns = [
    url(r'^collection/(?P<ids>(\w+))/$', views.collection, name='collection')
]