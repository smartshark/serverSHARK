from server.base import SUBSTITUTIONS


def create_substitutions_for_display():
    display_dict = {}
    for substitution, value in SUBSTITUTIONS.items():
        display_dict[value['name']] = value['description']

    return display_dict


def order_plugins(plugins):
    sorted_plugin_ids = []

    while len(sorted_plugin_ids) != len(plugins):
        for plugin_id, value in plugins.items():
            if plugin_id in sorted_plugin_ids:
                continue

            # If a plugin do not have any required plugins: add it
            if not value['plugin'].requires.all():
                sorted_plugin_ids.append(plugin_id)
            else:
                # Check if all requirements are met for the plugin. If yes: add it
                all_requirements_met = True
                for req_plugin in value['plugin'].requires.all():
                    if str(req_plugin.id) not in sorted_plugin_ids:
                        all_requirements_met = False

                if all_requirements_met:
                    sorted_plugin_ids.append(plugin_id)

    return_list = []
    for plugin_id in sorted_plugin_ids:
        return_list.append(plugins[plugin_id])

    return return_list