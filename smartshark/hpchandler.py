import os

import paramiko

from server import settings
from server.settings import HPC
from .scp import SCPClient


class HPCHandler(object):
    plugin_path = '~/bin/plugins'

    def __init__(self):
        self.username = HPC['username']
        self.password = HPC['password']
        self.host = HPC['host']
        self.port = HPC['port']

        self.ssh = self.create_ssh_client()

    def install_plugin(self, plugin):
        self.copy_plugin(plugin)
        self.execute_install(plugin)

    def delete_plugin(self, plugin):
        self.ssh.exec_command('rm -rf %s/%s' % (self.plugin_path, str(plugin)))

    def execute_install(self, plugin):
        command = "%s/install.sh " % self.plugin_path
        for arg in plugin.get_install_arguments():
            command += arg.name+" "

        print(command)
        plugin.installed = True
        plugin.save()

    def copy_plugin(self, plugin):
        scp = SCPClient(self.ssh.get_transport())

        # Copy plugin
        scp.put(plugin.get_full_path_to_archive(), remote_path=b'~')

        # Untar plugin
        (stdin, stdout, stderr) = self.ssh.exec_command('mkdir %s/%s' % (self.plugin_path, str(plugin)))
        (stdin, stdout, stderr) = self.ssh.exec_command('tar -C %s/%s -xvf %s' % (self.plugin_path, str(plugin),
                                                                                  plugin.get_name_of_archive()))
        if not str(stderr):
            raise Exception('Error in untaring plugin %s with archive located at %s.' %
                            (plugin.name, plugin.get_full_path_to_archive()))

        # Delete tar
        (stdin, stdout, stderr) = self.ssh.exec_command('rm -f ~/%s' % (plugin.get_name_of_archive()))
        if not str(stderr):
            raise Exception('Error in deleting tar of plugin %s with archive located at %s.' %
                            (plugin.name, plugin.get_full_path_to_archive()))

    def create_ssh_client(self):
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.host, 22, self.username, self.password)
        return client

