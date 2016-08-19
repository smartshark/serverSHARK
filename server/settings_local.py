from .base import *


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.9/howto/deployment/checklist/


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

#
#  SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = '6-og!lz7^&+f$cj#-0!68^rxm!#8$t=o&ypw)6d6a2t5_ntc1@'

HPC = {
    'username': 'jgrabow1',
    'password': 'aLD96neWVT',
    'host': 'gwdu102.gwdg.de',
    'port': 22,
    'queue': 'mpi',
    'node_properties': ['scratch']
}

# Database
# https://docs.djangoproject.com/en/1.9/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'smartshark',
        'USER': 'root',
        'PASSWORD': 'root',
        'HOST': 'localhost'
    },
    'mongodb' : {
        'ENGINE': '',
        'NAME': 'smartshark',
        'USER': 'root',
        'PASSWORD': 'balla1234$',
        'HOST': 'localhost',
        'PORT': 27017,
        'AUTHENTICATION_DB': 'admin'
    }
}