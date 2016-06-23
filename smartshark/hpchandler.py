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
            # if plugin operated on abstraction level, check execution type

            all_revisions_on_hpc = self.get_all_revision_paths(project)
            revisions_to_execute_plugin_on = []
            if execution == 'all':
                revisions_to_execute_plugin_on = all_revisions_on_hpc

            elif execution == 'rev':
                # If only some revisions (comma-separated list) need to be executed, create path and add it to list
                for revision in revisions.split(","):
                    revision_path = os.path.join(self.project_path, project.name, 'rev', revision)
                    revisions_to_execute_plugin_on.append(revision_path)

            elif execution == 'new':
                # Get all jobs that were executed with this plugin on this project
                jobs = plugin.get_all_jobs_for_project(project)
                job_revision_hashes = [job.revision_hash for job in jobs]

                # Go through all paths: If the revision was already processed by a job, it is not new, so exclude it
                for revision_path in all_revisions_on_hpc:
                    revision = os.path.basename(os.path.normpath(revision_path))
                    if revision not in job_revision_hashes:
                        revisions_to_execute_plugin_on.append(revision_path)

            elif execution == 'error':
                # Get all revisions on which this plugin failed (in some revisions) on this project. Important:
                # if the plugin on revision X failed in first run, but worked on revision X in the second it is not longer
                # marked as failing for this revision
                revisions = self.get_revisions_for_failed_plugins([plugin], project)
                for revision in revisions:
                    revision_path = os.path.join(self.project_path, project.name, 'rev', revision)
                    revisions_to_execute_plugin_on.append(revision_path)

            # Create command
            for revision_path in revisions_to_execute_plugin_on:
                # Create command
                command = string.Template(org_command).safe_substitute({
                        'path': revision_path,
                        'revision': os.path.basename(os.path.normpath(revision_path))
                    })
                # create command execution
                self.send_bsub_command(command, plugin, project, revision_path, plugin_execution)



    def send_bsub_command(self, command, plugin, project, revision, plugin_execution):
        (bsub_command, output_path, error_path) = self.generate_bsub_command(command, plugin, project)
        print(bsub_command)
        '''
        #TODO
        bsub_command = 'bsub -q mpi -o %s -e %s -J "vcsshark_vcsSHARK_0.11" ~/bin/req.sh test' % (output_path, error_path)
        output = self.execute_command(bsub_command)
        job_id_match = re.match(r"(\w*) <([0-9]*)>", output[-1])
        job_id = job_id_match.group(2)

        # Make db_user and db_password in bsub_command (if they are in the command) anonymous.
        bsub_command.replace(DATABASES['mongodb']['USER'], 'mongodbUser')
        bsub_command.replace(DATABASES['mongodb']['PASSWORD'], 'mongoPassword')

        revision_hash = None
        if plugin.abstraction_level == 'rev':
            revision_hash = os.path.basename(os.path.normpath(revision))

        job = Job(job_id=job_id, plugin_execution=plugin_execution, status='WAIT', output_log=output_path,
                  error_log=error_path, revision_path=revision, submission_string=bsub_command,
                  revision_hash=revision_hash)
        job.save()
        '''

    def update_job_information(self, jobs):
        # first check via bjobs output, if the job is found: use this status, if not check if there is an error log
        # if there are errors in it: there must be an error => state is exit

        for job in jobs:
            self.update_single_job_information(job)

    def update_single_job_information(self, job):
        # If job is already in exit state, it is fine
        if job.status in ['DONE', 'EXIT']:
            return

        # Try bjobs command (only some jobs are listed there) and update job
        found_job = self.check_bjobs_output(job)

        # If job is not found, try to get the error log. If the error log is empty the job was successful
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

    def get_revisions_for_failed_plugins(self, plugins, project):
        revisions = []
        for plugin in plugins:
            revisions.extend(list(plugin.get_revision_hashes_of_failed_jobs_for_project(project)))
        return revisions

    def prepare_project(self, project, plugins, execution, revisions):
        if execution is None or execution == '':
            execution = 'False'

        if revisions is None or revisions == '':
            revisions = 'False'

        if execution == 'error':
            revisions = self.get_revisions_for_failed_plugins(plugins, project)
            revisions = ','.join(revisions)
            execution = 'rev'



        plugin_types_str = ','.join([plugin.abstraction_level for plugin in plugins])
        self.execute_command('mkdir %s/%s' % (self.project_path, project.name), ignore_errors=True)

        command = 'python3.5 %s/preparer/main.py -u %s -out %s/%s -t %s -e %s -r %s' % (
            self.tools_path, project.url,
            self.project_path,
            project.name,
            plugin_types_str,
            execution,
            revisions
        )

        # If revisions are choosen but no revisions are given, we do not need to execute the preparer
        if execution == 'rev' and not revisions:
            return

        self.execute_command(command)

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
