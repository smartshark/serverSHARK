import abc


class CollectionConnector(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def install_plugins(self, plugins):
        return


    @abc.abstractmethod
    def execute_plugins(self, plugins, projects):
        return

    @abc.abstractmethod
    def delete_plugins(self, plugins):
        return

    @abc.abstractmethod
    def get_job_information(self, plugin_executions):
        return

