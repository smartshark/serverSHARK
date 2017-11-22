from .base import *

#  SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'CHANGEME'


DEBUG = True


LOCALQUEUE = {
    'root_path': '/tmp/servershark/',
    'plugin_installation': os.path.join(BASE_DIR, 'plugin_installations'),
    'plugin_output': os.path.join(BASE_DIR, 'plugin_output'),
    'redis_url': 'redis://localhost:6379',
    'job_queue': 'queue:jobs',
    'result_queue': 'queue:results',
    'timeout': 0,
    'debug': False,
}

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
}


COLLECTION_CONNECTOR_IDENTIFIER = 'LOCALQUEUE'

# Database
# https://docs.djangoproject.com/en/1.9/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'servershark',
        'USER': 'root',
        'PASSWORD': 'CHANGEME',
        'HOST': 'localhost'
    },
    'mongodb': {
        'ENGINE': '',
        'NAME': 'smartshark',
        'USER': 'root',
        'PASSWORD': 'CHANGEME',
        'HOST': 'localhost',
        'PORT': 27017,
        'AUTHENTICATION_DB': 'smartshark',
        'PLUGIN_SCHEMA_COLLECTION': 'plugin_schema',
        'SHARDING': False,
    }
}
