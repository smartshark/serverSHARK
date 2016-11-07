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
import sys

class HPCHandler(object):
    plugin_path = '~/bin/plugins'
    project_path = '/home/uni08/jgrabow1/bin/projects'
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

    def add_parameters_to_command(self, path_to_script, parameters):
        command = path_to_script
        for parameter in parameters:
            command += parameter["value"]+" "
        return command

    def create_execution_command(self, plugin, project, parameters):
        path_to_execute_script = "%s/%s/execute.sh " % (self.plugin_path, str(plugin))

        # Make execution script executable
        self.execute_command("chmod +x %s" % path_to_execute_script)

        # Add parameters
        command = self.add_parameters_to_command(path_to_execute_script, parameters)

        # Substitute stuff
        return string.Template(command).safe_substitute({
                'db_user': DATABASES['mongodb']['USER'],
                'db_password': DATABASES['mongodb']['PASSWORD'],
                'db_database': DATABASES['mongodb']['NAME'],
                'db_hostname': DATABASES['mongodb']['HOST'],
                'db_port': DATABASES['mongodb']['PORT'],
                'db_authentication': DATABASES['mongodb']['AUTHENTICATION_DB'],
                'url': project.url,
                'plugin_path': os.path.join(self.plugin_path, str(plugin))
        })

    def create_install_command(self, plugin, parameters):
        path_to_install_script = "%s/%s/install.sh " % (self.plugin_path, str(plugin))

        # Make execution script executable
        self.execute_command("chmod +x %s" % path_to_install_script)

        # Add parameters
        command = self.add_parameters_to_command(path_to_install_script, parameters)

        return string.Template(command).substitute({
            'plugin_path': os.path.join(self.plugin_path, str(plugin))
        })

    def execute_install(self, plugin, parameters):
        # Build parameter for install script.
        command = self.create_install_command(plugin, parameters)

        self.execute_command(command)

    def execute_plugin(self, plugin, project, parameters, execution, revisions):
        org_command = self.create_execution_command(plugin, project, parameters)
        path_to_repo = os.path.join(self.project_path, project.name, 'base')

        # Create plugin execution
        plugin_execution = PluginExecution(project=project, plugin=plugin)
        plugin_execution.save()

        # if plugin operates on rep or other level, execute it once
        if plugin.abstraction_level == 'repo' or plugin.abstraction_level == 'other':
            command = string.Template(org_command).safe_substitute({
                'path': path_to_repo
            })

            # create command execution
            self.send_bsub_command(command, plugin, project, None, plugin_execution)

        elif plugin.abstraction_level == 'rev':
            # if plugin operated on abstraction level, check execution type
            all_revisions = self.get_all_revisions(project)
            revisions_to_execute_plugin_on = []

            if execution == 'all':
                revisions_to_execute_plugin_on = all_revisions

            elif execution == 'rev':
                if len(revisions.split(",")) == 1:
                    revisions_to_execute_plugin_on.append(revisions)
                else:
                    # If only some revisions (comma-separated list) need to be executed, create path and add it to list
                    for revision in revisions.split(","):
                        revisions_to_execute_plugin_on.append(revision)

            elif execution == 'new':
                # Get all jobs that were executed with this plugin on this project
                jobs = plugin.get_all_jobs_for_project(project)
                job_revision_hashes = [job.revision_hash for job in jobs]

                # Go through all paths: If the revision was already processed by a job, it is not new, so exclude it
                for revision in all_revisions:
                    if revision not in job_revision_hashes:
                        revisions_to_execute_plugin_on.append(revision)

            elif execution == 'error':
                # Get all revisions on which this plugin failed (in some revisions) on this project. Important:
                # if the plugin on revision X failed in first run, but worked on revision X in the second it is not longer
                # marked as failing for this revision
                revisions = self.get_revisions_for_failed_plugins([plugin], project)
                for revision in revisions:
                    revisions_to_execute_plugin_on.append(revision)

            # Create command
            for revision in revisions_to_execute_plugin_on:
                # Create command
                command = string.Template(org_command).safe_substitute({
                        'path': path_to_repo,
                        'revision': revision
                })
                # create command execution
                self.send_bsub_command(command, plugin, project, revision, plugin_execution)

    def send_bsub_command(self, command, plugin, project, revision, plugin_execution):
        (bsub_command, output_path, error_path) = self.generate_bsub_command(command, plugin, project)

        output = self.execute_command(bsub_command)

        job_id = None
        for line in output:
            if line.startswith("Job"):
                job_id_match = re.match(r"(\w*) <([0-9]*)>", line)
                job_id = job_id_match.group(2)

        # Make db_user and db_password in bsub_command (if they are in the command) anonymous.
        bsub_command = bsub_command.replace(DATABASES['mongodb']['USER'], 'mongodbUser')
        bsub_command = bsub_command.replace(DATABASES['mongodb']['PASSWORD'], 'mongoPassword')

        if plugin.abstraction_level == 'rev':
            job = Job(job_id=job_id, plugin_execution=plugin_execution, status='WAIT', output_log=output_path,
                      error_log=error_path, submission_string=bsub_command,
                      revision_hash=revision)
        else:
            job = Job(job_id=job_id, plugin_execution=plugin_execution, status='WAIT', output_log=output_path,
                      error_log=error_path, submission_string=bsub_command)

        job.save()

    def update_job_information(self, jobs):
        # first check via bjobs output, if the job is found: use this status, if not check if there is an error log
        # if there are errors in it: there must be an error => state is exit

        for job in jobs:
            # set if output exists or not
            out_exists, error_exists = self.does_output_files_exist(job)
            job.output_file_exists = out_exists
            job.error_file_exists = error_exists

            self.update_single_job_information(job)

    def update_single_job_information(self, job):
        # If job is already in exit state, it is fine
        if job.status in ['DONE', 'EXIT']:
            return

        if job.output_file_exists is False or job.error_file_exists is False:
            job.status = 'WAIT'
            job.save()
            return

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

    def does_output_files_exist(self, job):
        if job.status in ['DONE', 'EXIT']:
            return True, True

        error_path = job.error_log.replace('~', self.home_folder)
        output_path = job.output_log.replace('~', self.home_folder)

        error_exists = True
        try:
            self.execute_command('head %s' % error_path)
        except Exception:
            error_exists = False

        out_exists = True
        try:
            self.execute_command('head %s' % output_path)
        except Exception:
            out_exists = False

        return out_exists, error_exists


    def get_output_log(self, job):
        sftp_client = self.ssh.get_ssh_client().open_sftp()
        try:
            remote_file = sftp_client.open(job.output_log.replace('~', self.home_folder))
        except FileNotFoundError:
            return None

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
        try:
            remote_file = sftp_client.open(error_path.replace('~', self.home_folder))
        except FileNotFoundError:
            return None

        output = []
        try:
            for line in remote_file:
                output.append(line.strip())
        finally:
            remote_file.close()

        return output

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
                bsub_command += "ended(%s_%s) && " % (project.name, str(plugin))

            bsub_command = bsub_command[:-4]
            bsub_command += "' "

        for node_property in self.node_properties:
            bsub_command += "-R %s " % node_property

        bsub_command += "%s" % command

        return (bsub_command, output_path, error_path)

    def get_base_directory(self, project):
        return os.path.join(self.project_path, project.name, 'base')

    def get_all_revisions(self, project):
        path = os.path.join(self.project_path, project.name, 'rev')
        self.execute_command('cd %s' % self.get_base_directory(project))
        self.execute_command('git log --pretty=oneline --all --reverse > revisions.txt')
        sftp_client = self.ssh.get_ssh_client().open_sftp()
        remote_file = sftp_client.open(os.path.join(self.get_base_directory(project), 'revisions.txt'))
        revisions = []
        try:
            for line in remote_file:
                if line:
                    revisions.append(line.strip().split(" ")[0])
        finally:
            remote_file.close()
            self.execute_command('rm -rf %s' % os.path.join(self.get_base_directory(project), 'revisions.txt'))

        return revisions

    def get_revisions_for_failed_plugins(self, plugins, project):
        revisions = []
        for plugin in plugins:
            revisions.extend(plugin.get_revision_hashes_of_failed_jobs_for_project(project))
        return revisions


    def is_base_repo_existent(self, project):
        out = self.execute_command('ls %s' % os.path.join(self.project_path, project.name))
        folders = []

        if out:
            folders = out[0].strip().split(" ")

        if 'base' in folders:
            return True

        return False

    def prepare_project(self, project, plugins, execution, revisions):

        # Create project folder if not existent
        self.execute_command('mkdir %s' % os.path.join(self.project_path, project.name), ignore_errors=True)

        # Execute git clone into base folder
        if self.is_base_repo_existent(project):
            self.execute_command('cd %s' % self.get_base_directory(project))
            self.execute_command('git pull')
        else:
            self.execute_command('git clone %s %s' % (project.url, self.get_base_directory(project)))

    def install_plugin(self, plugin, parameters):
        self.copy_plugin(plugin)
        self.execute_install(plugin, parameters)

    def delete_plugin(self, plugin):
        self.execute_command('rm -rf %s/%s' % (self.plugin_path, str(plugin)))

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
        print("Execute command: %s" % command)
        (stdin, stdout, stderr) = self.ssh.execute(command)

        if stderr and not ignore_errors:
            raise Exception('Error in executing command %s! Error: %s.' % (command, ','.join(stderr)))

        return stdout
