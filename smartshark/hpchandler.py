import os

import paramiko

from server import settings
from server.settings import HPC
from server.settings import DATABASES
from smartshark.shellhandler import ShellHandler
from .scp import SCPClient
import string
import logging

class HPCHandler(object):
    plugin_path = '~/bin/plugins'
    project_path = '~/bin/projects'
    tools_path = '~/bin/tools'
    bsub_output_path = '~/bin/output/out.txt'
    bsub_err_path = '~/bin/output/err.txt'

    def __init__(self):
        self.username = HPC['username']
        self.password = HPC['password']
        self.host = HPC['host']
        self.port = HPC['port']
        self.queue = HPC['queue']
        self.node_properties = HPC['node_properties']

        self.logger = logging.getLogger(__name__)

        self.ssh = ShellHandler(self.host, self.username, self.password, self.port)

    def execute_plugin(self, plugin, project, parameters):
        path_to_execute_script = "%s/%s/execute.sh " % (self.plugin_path, str(plugin))
        self.execute_command("chmod +x %s" % path_to_execute_script)

        command = path_to_execute_script
        for parameter in parameters:
            command += parameter["value"]+" "

        org_command = string.Template(command).safe_substitute({
                'db_user': DATABASES['mongodb']['USER'],
                'db_password': DATABASES['mongodb']['PASSWORD'],
                'db_database': DATABASES['mongodb']['NAME'],
                'db_hostname': DATABASES['mongodb']['HOST'],
                'db_port': DATABASES['mongodb']['PORT'],
                'db_authentication': DATABASES['mongodb']['AUTHENTICATION_DB'],
        })

        # if plugin operates on rep or other level, execute it once
        if plugin.abstraction_level == 'repo' or plugin.abstraction_level == 'other':
            command = string.Template(org_command).safe_substitute({
                'path': os.path.join(self.project_path, project.name, 'repo')
            })

            # create command execution
            print(self.generate_bsub_command(command, project.name+"_"+str(plugin), plugin.requires.all(), project))
        elif plugin.abstraction_level == 'rev':
            for revison_path in self.get_all_revision_paths(project):
                command = string.Template(org_command).safe_substitute({
                    'path': revison_path
                })

                # create command execution
                print(self.generate_bsub_command(command, project.name+"_"+str(plugin), plugin.requires.all(), project))

    def generate_bsub_command(self, command, jobname, plugin_dependencies, project):
        bsub_command = 'bsub -q %s -o %s -e %s -J "%s" ' % (
            self.queue, self.bsub_output_path, self.bsub_err_path, jobname
        )

        if plugin_dependencies:
            bsub_command += "-w '"
            for plugin in plugin_dependencies:
                bsub_command += "done(%s_%s) && " % (project.name, str(plugin))

            bsub_command = bsub_command[:-4]
            bsub_command += "' "

        for node_property in self.node_properties:
            bsub_command += "-R %s " % node_property

        bsub_command += "%s" % command

        return bsub_command


    def get_all_revision_paths(self, project):
        path = os.path.join(self.project_path, project.name, 'rev')
        out = self.execute_command('ls %s' % path)

        revision_paths = []
        for revision in out:
            revision_paths.append(os.path.join(path, revision.rstrip()))

        return revision_paths


    def prepare_project(self, project, plugin_types):
        plugin_types_str = ','.join(plugin_types)
        self.execute_command('rm -rf %s/%s' % (self.project_path, project.name))
        self.execute_command('mkdir %s/%s' % (self.project_path, project.name))
        self.execute_command('python3.5 %s/preparer/main.py -u %s -out %s/%s -t %s' % (self.tools_path, project.url,
                                                                                       self.project_path, project.name,
                                                                                       plugin_types_str))

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

        command = string.Template(command).substitute({'plugin_path': os.path.join(self.plugin_path, str(plugin))})

        self.execute_command("chmod +x %s" % path_to_install_script)
        self.execute_command(command)

    def copy_plugin(self, plugin):
        scp = SCPClient(self.ssh.get_ssh_client().get_transport())

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

    def execute_command(self, command):
        print("Excute command: %s" % command)
        (stdin, stdout, stderr) = self.ssh.execute(command)

        if stderr:
            raise Exception('Error in executing command %s! Error: %s.' % (command, ','.join(stderr)))

        return stdout