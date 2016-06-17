import os

import paramiko

from server import settings
from server.settings import HPC
from server.settings import DATABASES
from smartshark.models import PluginExecution, Job
from smartshark.shellhandler import ShellHandler
from .scp import SCPClient
import string
import uuid
import logging
import re

class HPCHandler(object):
    plugin_path = '~/bin/plugins'
    project_path = '~/bin/projects'
    tools_path = '~/bin/tools'
    bsub_output_path = '~/bin/output'
    home_folder = '/usr/users/jgrabow1'

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
                'url': project.url,
        })

        # Create plugin execution
        plugin_execution = PluginExecution(project=project, plugin=plugin)
        plugin_execution.save()

        # if plugin operates on rep or other level, execute it once
        if plugin.abstraction_level == 'repo' or plugin.abstraction_level == 'other':
            path_to_repo = os.path.join(self.project_path, project.name, 'repo')
            command = string.Template(org_command).safe_substitute({
                'path': path_to_repo
            })

            # create command execution
            self.send_bsub_command(command, plugin, project, path_to_repo, plugin_execution)
        elif plugin.abstraction_level == 'rev':
            for revision_path in self.get_all_revision_paths(project):
                command = string.Template(org_command).safe_substitute({
                    'path': revision_path,
                    'revision': os.path.basename(os.path.normpath(revision_path))
                })

                # create command execution
                self.send_bsub_command(command, plugin, project, revision_path, plugin_execution)

    def send_bsub_command(self, command, plugin, project, revision, plugin_execution):
        (bsub_command, output_path, error_path) = self.generate_bsub_command(command, plugin, project)

        #TODO
        bsub_command = 'bsub -q mpi -o %s -e %s -J "vcsshark_vcsSHARK_0.11" ~/bin/req.sh test' % (output_path, error_path)
        output = self.execute_command(bsub_command)
        job_id_match = re.match(r"(\w*) <([0-9]*)>", output[-1])
        job_id = job_id_match.group(2)

        job = Job(job_id=job_id, plugin_execution=plugin_execution, status='WAIT', output_log=output_path,
                  error_log=error_path, revision_path=revision, submission_string=bsub_command)
        job.save()

    def update_job_information(self, jobs):
        # first check via bjobs output, if the job is found: use this status, if not check if there is an error log
        # if there are errors in it: there must be an error => state is exit

        for job in jobs:
            found_job = self.check_bjobs_output(job)
            if not found_job:
                error_log = self.get_error_log(job)

                if not error_log:
                    job.status = 'DONE'
                else:
                    job.status = 'EXIT'
                job.save()

    def get_history(self, job):
        out = self.execute_command('bhist -l %s' % job.job_id)
        out = [line.strip() for line in out]
        if 'No matching job found' in out[0]:
            return []

        return out

    def get_output_log(self, job):
        sftp_client = self.ssh.get_ssh_client().open_sftp()
        remote_file = sftp_client.open(job.output_log.replace('~', self.home_folder))
        output = []
        try:
            for line in remote_file:
                output.append(line.strip())
        finally:
            remote_file.close()

        return output

    def get_error_log(self, job):
        error_path = job.error_log
        sftp_client = self.ssh.get_ssh_client().open_sftp()
        remote_file = sftp_client.open(error_path.replace('~', self.home_folder))

        output = []
        try:
            for line in remote_file:
                output.append(line.strip())
        finally:
            remote_file.close()

        return output

    def check_bjobs_output(self, job):
        out = self.execute_command('bjobs -noheader -w %s' % job.job_id)

        if 'not found' in out[0]:
            return False

        output_parts = out[0].split(" ")
        job.status = output_parts[2]
        job.save()
        return True

    def generate_bsub_command(self, command, plugin, project):
        jobname = project.name+"_"+str(plugin)
        plugin_dependencies = plugin.requires.all()

        generated_uuid = str(uuid.uuid4())
        output_path = os.path.join(self.bsub_output_path, generated_uuid+"_out.txt")
        error_path = os.path.join(self.bsub_output_path, generated_uuid+"_error.txt")

        bsub_command = 'bsub -q %s -o %s -e %s -J "%s" ' % (
            self.queue, output_path, error_path, jobname
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

        return (bsub_command, output_path, error_path)


    def get_all_revision_paths(self, project):
        path = os.path.join(self.project_path, project.name, 'rev')
        out = self.execute_command('ls %s' % path)

        revision_paths = []
        for revision in out:
            revision_paths.append(os.path.join(path, revision.rstrip()))

        return revision_paths

    def prepare_project(self, project, plugin_types, force_renew):
        plugin_types_str = ','.join(plugin_types)
        self.execute_command('mkdir %s/%s' % (self.project_path, project.name), ignore_errors=True)

        command = 'python3.5 %s/preparer/main.py -u %s -out %s/%s -t %s' % (self.tools_path, project.url,
                                                                            self.project_path, project.name,
                                                                            plugin_types_str,
                                                                            )
        if force_renew:
            command += ' -f'

        self.execute_command(command)

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

    def execute_command(self, command, ignore_errors=False):
        print("Excute command: %s" % command)
        (stdin, stdout, stderr) = self.ssh.execute(command)

        if stderr and not ignore_errors:
            raise Exception('Error in executing command %s! Error: %s.' % (command, ','.join(stderr)))

        return stdout
