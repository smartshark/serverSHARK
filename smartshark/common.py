from .models import Plugin


def find_required_plugins(req_plugin):
    if req_plugin['operator'] == '>=':
        db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version__gte=req_plugin['version'])
    elif req_plugin['operator'] == '<=':
        db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version__lte=req_plugin['version'])
    elif req_plugin['operator'] == '>':
        db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version__gt=req_plugin['version'])
    elif req_plugin['operator'] == '<':
        db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version__lt=req_plugin['version'])
    else:
        db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version=req_plugin['version'])

    if len(db_plugins) > 1:
        return max(db_plugins, key=lambda x:x.version)
    elif len(db_plugins) > 0:
        return db_plugins[0]
    else:
        return None
