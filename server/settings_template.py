from .base import *


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.9/howto/deployment/checklist/


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

#
#  SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'xxxx'

HPC = {
    'username': 'xxx',
    'password': 'xxx',
    'host': 'xxx',
    'port': 22,
    'queue': 'xx',
    'node_properties': [],
    'root_path': 'xxx',
    'log_path': 'xxx'
}

AZURE = {

}

SPARK_MASTER = {
    'host': 'xx',
    'port': 'xx',
}

COLLECTION_CONNECTOR_IDENTIFIER = 'GWDG'

# Database
# https://docs.djangoproject.com/en/1.9/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'xx',
        'USER': 'xx',
        'PASSWORD': 'xx',
        'HOST': 'xx'
    },
    'mongodb' : {
        'ENGINE': '',
        'NAME': 'xx',
        'USER': 'xx',
        'PASSWORD': 'xx',
        'HOST': 'xx',
        'PORT': 27017,
        'AUTHENTICATION_DB': 'xx',
        'PLUGIN_SCHEMA_COLLECTION': 'plugin_schema'
    }
}

