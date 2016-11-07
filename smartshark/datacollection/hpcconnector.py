import os
import string
import subprocess
import threading
import timeit
import uuid
import logging

from server.settings import HPC, DATABASES

from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface
from smartshark.models import ExecutionHistory, Job
from smartshark.scp import SCPClient
from smartshark.shellhandler import ShellHandler

logger = logging.getLogger('hpcconnector')


class HPCConnector(PluginManagementInterface):
    """
    Connector for the HPC cluster of the GWDG.

    plugins are installed to: root_path/plugins/<plugin_name>_<plugin_version>
    projects are cloned to: root_path/projects/<project_name>
    logs are saved to: log_path/<job_id>(_out|_err).txt


    """
    def __init__(self):
        self.username = HPC['username']
        self.password = HPC['password']
        self.host = HPC['host']
        self.port = HPC['port']
        self.queue = HPC['queue']
        self.node_properties = HPC['node_properties']
        self.plugin_path = os.path.join(HPC['root_path'], 'plugins')
        self.project_path = os.path.join(HPC['root_path'], 'projects')
        self.log_path = HPC['log_path']

        self.ssh = ShellHandler(self.host, self.username, self.password, self.port)

    @property
    def identifier(self):
        return 'GWDG'

    def generate_plugin_execution_command(self, plugin_execution):
        path_to_execute_script = "%s/%s/execute.sh " % (self.plugin_path, str(plugin_execution.plugin))

        # Add parameters
        command = path_to_execute_script+plugin_execution.get_sorted_argument_values()

        # Substitute stuff
        return string.Template(command).safe_substitute({
                'db_user': DATABASES['mongodb']['USER'],
                'db_password': DATABASES['mongodb']['PASSWORD'],
                'db_database': DATABASES['mongodb']['NAME'],
                'db_hostname': DATABASES['mongodb']['HOST'],
                'db_port': DATABASES['mongodb']['PORT'],
                'db_authentication': DATABASES['mongodb']['AUTHENTICATION_DB'],
                'url': plugin_execution.project.url,
                'plugin_path': os.path.join(self.plugin_path, str(plugin_execution.plugin))
        })

    def generate_bsub_command(self, plugin_command, job):
        output_path = os.path.join(self.log_path, str(job.id)+'_out.txt')
        error_path = os.path.join(self.log_path, str(job.id)+'_err.txt')

        bsub_command = 'bsub -q %s -o %s -e %s -J "%s" ' % (
            self.queue, output_path, error_path, str(job.id)
        )

        req_jobs = job.requires.all()
        if req_jobs:
            bsub_command += "-w '"
            for req_job in req_jobs:
                bsub_command += 'ended("%s") && ' % str(req_job.id)

            bsub_command = bsub_command[:-4]
            bsub_command += "' "

        for node_property in self.node_properties:
            bsub_command += "-R %s " % node_property

        command = string.Template(plugin_command).safe_substitute({
            'path': os.path.join(self.project_path, job.plugin_execution.project.name),
            'revision': job.revision_hash
        })

        full_cmd = "%s%s" % (bsub_command, command)
        logger.debug('Generated bsub command: %s' % full_cmd)

        return full_cmd

    def get_sent_bash_command(self, job):
        plugin_command = self.generate_plugin_execution_command(job.plugin_execution)
        return self.generate_bsub_command(plugin_command, job)

    def execute_plugins(self, project, jobs, plugin_executions):
        # Prepare project (clone / pull)
        logger.info('Preparing project...')
        self.prepare_project(project)

        logger.info('Generating bsub script...')
        commands = []
        for plugin_execution in plugin_executions:
            plugin_command = self.generate_plugin_execution_command(plugin_execution)
            jobs = Job.objects.filter(plugin_execution=plugin_execution).all()

            for job in jobs:
                commands.append(self.generate_bsub_command(plugin_command, job))

        logger.info('Sending and executing bsub script...')
        self.send_and_execute_file(commands, False)

    def prepare_project(self, project):
        # Create project folder if not existent
        try:
            self.execute_command('mkdir %s' % os.path.join(self.project_path, project.name))
            self.execute_command('git clone %s %s' % (project.url, os.path.join(self.project_path, project.name)))
        except Exception:
            self.execute_command('cd %s && git pull > /dev/null 2>&1' % os.path.join(self.project_path, project.name))

    def get_output_log(self, job):
        sftp_client = self.ssh.get_ssh_client().open_sftp()
        try:
            remote_file = sftp_client.open(os.path.join(self.log_path, str(job.id)+'_out.txt'))
        except FileNotFoundError:
            return ['File Not Found']

        output = []
        try:
            for line in remote_file:
                output.append(line.strip())
        finally:
            remote_file.close()

        return output

    def get_error_log(self, job):
        sftp_client = self.ssh.get_ssh_client().open_sftp()
        try:
            remote_file = sftp_client.open(os.path.join(self.log_path, str(job.id)+'_err.txt'))
        except FileNotFoundError:
            return ['File Not Found']

        output = []
        try:
            for line in remote_file:
                output.append(line.strip())
        finally:
            remote_file.close()

        return output

    def get_job_stati(self, jobs):
        if not jobs:
            return []

        job_status_list = []
        commands = []
        for job in jobs:
            error_path = os.path.join(self.log_path, str(job.id)+'_err.txt')
            commands.append("wc -c < %s" % error_path)

        out = self.send_and_execute_file(commands, True)
        logger.debug(out)
        for out_line in out:
            out_line = out_line.strip()
            if out_line == '0':
                job_status_list.append('DONE')
            elif 'No such file or directory' in out_line:
                job_status_list.append('WAIT')
            else:
                job_status_list.append('EXIT')

        logger.debug(job_status_list)
        return job_status_list

    def delete_plugins(self, plugins):
        for plugin in plugins:
            self.delete_plugin(plugin)

    def delete_plugin(self, plugin):
        self.execute_command('rm -rf %s/%s' % (self.plugin_path, str(plugin)))

    def install_plugins(self, plugins):
        installations = []
        for plugin in plugins:
            try:
                self.copy_plugin(plugin)
                self.execute_install(plugin)
                installations.append((True, None))
            except Exception as e:
                installations.append((False, str(e)))

        return installations

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

    def execute_install(self, plugin):
        # Build parameter for install script.
        command = self.create_install_command(plugin)
        self.execute_command(command)

    def create_install_command(self, plugin):
        path_to_install_script = "%s/%s/install.sh " % (self.plugin_path, str(plugin))

        # Make execution script executable
        self.execute_command("chmod +x %s" % path_to_install_script)

        # Add parameters
        command = self.add_parameters_to_install_command(path_to_install_script, plugin)

        return string.Template(command).substitute({
            'plugin_path': os.path.join(self.plugin_path, str(plugin))
        })

    def add_parameters_to_install_command(self, path_to_script, plugin):
        command = path_to_script

        for argument in plugin.argument_set.all().filter(type='install').order_by('position'):
            command += argument.install_value+" "

        return command

    def execute_command(self, command, ignore_errors=False, combine_stderr_stdout=False):
        logging.info('Execute command: %s' % command)
        (stdout, stderr) = self.ssh.execute(command, stderr_stdout_combined=combine_stderr_stdout)

        logging.debug('Output: %s' % ' '.join(stdout))
        logging.debug('ErrorOut: %s' % ' '.join(stderr))
        if stderr and not ignore_errors:
            raise Exception('Error in executing command %s! Error: %s.' % (command, ','.join(stderr)))

        return stdout

    def send_and_execute_file(self, commands, order_needed):
        generated_uuid = str(uuid.uuid4())
        path_to_sh_file = os.path.join(os.path.dirname(__file__), 'temp', generated_uuid+'.sh')
        path_to_remote_sh_file = os.path.join(self.project_path, generated_uuid+'.sh')
        with open(path_to_sh_file, 'w') as shell_file:
            shell_file.write("#!/bin/sh\n")

            for line in commands:
                shell_file.write("%s\n" % line)
            shell_file.write("rm -rf %s\n" % path_to_remote_sh_file)

        # Copy Shell file with jobs to execute
        scp = SCPClient(self.ssh.get_ssh_client().get_transport())
        scp.put(path_to_sh_file, remote_path=b'%s' % str.encode(path_to_remote_sh_file))

        # Delete local file
        subprocess.run(['rm', '-rf', path_to_sh_file])

        # Make remote file executable
        self.execute_command('chmod +x %s' % path_to_remote_sh_file)

        # Execute. We need the variable order_needed as it distighushes between two separate possible execution methods
        logging.info("Execute command: %s" % path_to_remote_sh_file)
        if order_needed:
            out = self.ssh.execute_file(path_to_remote_sh_file, order_needed)
        else:
            thread = threading.Thread(target=self.ssh.execute_file, args=(path_to_remote_sh_file, order_needed))
            thread.start()
            out = []

        logging.debug('Output: %s' % ' '.join(out))

        return out
