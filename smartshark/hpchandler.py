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

    def execute_plugin(self, plugin, project, parameters):
        pass

    def install_plugin(self, plugin, parameters):
        self.copy_plugin(plugin)
        self.execute_install(plugin, parameters)

    def delete_plugin(self, plugin):
        self.execute_command('rm -rf %s/%s' % (self.plugin_path, str(plugin)))

    def execute_install(self, plugin, parameters):
        # Build parameter for install script.
        path_to_install_script = "%s/%s/install.sh " % (self.plugin_path, str(plugin))
        command = path_to_install_script
        for parameter in parameters:
            command += parameter['value']+" "

        print(command)

        self.execute_command("chmod +x %s" % path_to_install_script)
        self.execute_command(command)

    def copy_plugin(self, plugin):
        scp = SCPClient(self.ssh.get_transport())

        # Copy plugin
        scp.put(plugin.get_full_path_to_archive(), remote_path=b'~')

        # Untar plugin
        try:
            self.delete_plugin(plugin)
        except Exception:
            pass

        self.execute_command('mkdir %s/%s' % (self.plugin_path, str(plugin)))
        self.execute_command('tar -C %s/%s -xvf %s' % (self.plugin_path, str(plugin), plugin.get_name_of_archive()))

        # Delete tar
        self.execute_command('rm -f ~/%s' % (plugin.get_name_of_archive()))

    def create_ssh_client(self):
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.host, 22, self.username, self.password)
        return client

    def execute_command(self, command):
        (stdin, stdout, stderr) = self.ssh.exec_command(command)
        std_err = stderr.readlines()

        if std_err:
            raise Exception('Error in executing command %s! Error: %s.' % (command, std_err))