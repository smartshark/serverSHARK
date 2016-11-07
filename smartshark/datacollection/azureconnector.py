from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface


class AzureConnector(PluginManagementInterface):
    def __init__(self):
        pass

    @property
    def identifier(self):
        return 'AZURE'

    def execute_plugins(self, project, jobs, plugin_executions):
        pass

    def get_job_stati(self, jobs):
        pass

    def get_output_log(self, job):
        pass

    def get_error_log(self, job):
        pass

    def get_sent_bash_command(self, job):
        return

    def delete_plugins(self, plugins):
        pass

    def install_plugins(self, plugins):
        pass