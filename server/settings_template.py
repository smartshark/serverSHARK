from .base import *


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.9/howto/deployment/checklist/


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

#
#  SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'xxxx'

# Token for (limited) remote access
API_KEY =None

HPC = {
    'username': 'xxx',
    'password': 'xxx',
    'host': 'xxx',
    'port': 22,
    'queue': 'xx',
    'node_properties': [],
    'root_path': 'xxx',
    'log_path': 'xxx',
    'ssh_tunnel_username': '',
    'ssh_tunnel_password': '',
    'ssh_tunnel_host': '',
    'ssh_tunnel_port': '',
    'ssh_use_tunnel': '',
    'cores_per_job': 4,
    'local_log_path': ''
}

AZURE = {

}

SPARK_MASTER = {
    'host': 'xx',
    'port': 'xx',
}

LOCALQUEUE = {
    'root_path': '/tmp/servershark/',
    'redis_url': 'redis://localhost:6379',
    'plugin_installation': os.path.join(BASE_DIR, 'plugin_installations'),
    'plugin_output': os.path.join(BASE_DIR, 'plugin_output'),
    'job_queue': 'queue:jobs',
    'result_queue': 'queue:results',
    'timeout': 120,
    'debug': False,
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
    'mongodb': {
        'ENGINE': '',
        'NAME': 'xx',
        'USER': 'xx',
        'PASSWORD': 'xx',
        'HOST': 'xx',
        'PORT': 27017,
        'AUTHENTICATION_DB': 'xx',
        'PLUGIN_SCHEMA_COLLECTION': 'plugin_schema',
        'SHARDING': False
    }
}


EMAIL_HOST = ''
EMAIL_PORT = 587
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
EMAIL_USE_TLS = True
NOTIFICATION_RECEIVER = ''