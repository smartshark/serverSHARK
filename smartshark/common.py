from smartshark.mongohandler import handler

from server.base import SUBSTITUTIONS
from django.contrib import messages

def create_substitutions_for_display():
    display_dict = {}
    for substitution, value in SUBSTITUTIONS.items():
        display_dict[value['name']] = value['description']

    return display_dict


def order_plugins(plugins):
    sorted_plugins = []

    while len(sorted_plugins) != len(plugins):
        for plugin in plugins:
            if plugin in sorted_plugins:
                continue

            # If a plugin do not have any required plugins: add it
            # Or if not all required plugins are in the plugin list
            if not plugin.requires.all() or not all(plugin in plugins for plugin in plugin.requires.all()):
                sorted_plugins.append(plugin)
            else:
                # Check if all requirements are met for the plugin. If yes: add it
                all_requirements_met = True
                for req_plugin in plugin.requires.all():
                    if req_plugin not in sorted_plugins:
                        all_requirements_met = False

                if all_requirements_met:
                    sorted_plugins.append(plugin)

    return sorted_plugins


def append_success_messages_to_req(plugin_action, plugins, request):
    i = 0
    for action_status in plugin_action:
        plugin = plugins[i]

        if action_status[0]:
            plugin.installed = True
            plugin.save()

            messages.success(request, 'Successfully installed/executed plugin %s in version %s' %
                             (plugin.name, plugin.version))
        else:
            messages.error(request, 'Plugin %s was not installed/executed! Message: %s' % (plugin,
                                                                                           action_status[1]))

        i += 1
