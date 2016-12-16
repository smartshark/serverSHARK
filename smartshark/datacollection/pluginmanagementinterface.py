import abc
import os
import sys

from server.settings import COLLECTION_CONNECTOR_IDENTIFIER


class PluginManagementInterface(metaclass=abc.ABCMeta):

    @abc.abstractproperty
    def identifier(self):
        return

    @abc.abstractmethod
    def install_plugins(self, plugins):
        return

    @abc.abstractmethod
    def execute_plugins(self, project, jobs, plugin_executions):
        return

    @abc.abstractmethod
    def delete_plugins(self, plugins):
        return

    @abc.abstractmethod
    def get_job_stati(self, jobs):
        return

    @abc.abstractmethod
    def get_output_log(self, job):
        return

    @abc.abstractmethod
    def get_error_log(self, job):
        return

    @abc.abstractmethod
    def get_sent_bash_command(self, job):
        return

    @abc.abstractmethod
    def delete_output_for_plugin_execution(self, plugin_execution):
        return

    @staticmethod
    def find_correct_plugin_manager():
        plugin_files = [x[:-3] for x in os.listdir(os.path.dirname(os.path.realpath(__file__))) if x.endswith(".py")]
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        for plugin in plugin_files:
            __import__(plugin)

        for sc in PluginManagementInterface.__subclasses__():
            manager = sc()
            if manager.identifier == COLLECTION_CONNECTOR_IDENTIFIER:
                return manager

        return None
