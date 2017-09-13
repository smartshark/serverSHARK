import os
import string
import subprocess
import threading
import sys
import uuid
import logging

from server.settings import HPC, DATABASES

from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface
from smartshark.models import ExecutionHistory, Job
from smartshark.scp import SCPClient
from smartshark.shellhandler import ShellHandler

logger = logging.getLogger('hpcconnector')


class JobSubmissionThread(threading.Thread):
    def __init__(self, path_to_remote_file, host, username, password, port, tunnel_host, tunnel_username,
                 tunnel_password, tunnel_port, use_tunnel):
        threading.Thread.__init__(self)
        self.remote_file = path_to_remote_file
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.tunnel_host = tunnel_host
        self.tunnel_username = tunnel_username
        self.tunnel_password = tunnel_password
        self.tunnel_port = tunnel_port
        self.use_tunnel = use_tunnel

    def run(self):
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10020) as handler:
            out, err = handler.execute_file(self.remote_file, False)
            logger.debug(out)
            logger.debug(err)


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
        self.tunnel_username = HPC['ssh_tunnel_username']
        self.tunnel_password = HPC['ssh_tunnel_password']
        self.tunnel_host = HPC['ssh_tunnel_host']
        self.tunnel_port = HPC['ssh_tunnel_port']
        self.use_tunnel = HPC['ssh_use_tunnel']

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
                'project_name': plugin_execution.project.name,
                'plugin_path': os.path.join(self.plugin_path, str(plugin_execution.plugin))
        })

    def generate_bsub_command(self, plugin_command, job, plugin_execution_output_path):
        output_path = os.path.join(plugin_execution_output_path, str(job.id)+'_out.txt')
        error_path = os.path.join(plugin_execution_output_path, str(job.id)+'_err.txt')

        bsub_command = 'bsub -W 48:00 -q %s -o %s -e %s -J "%s" ' % (
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
        plugin_execution_output_path = os.path.join(self.log_path, str(job.plugin_execution.id))
        return self.generate_bsub_command(plugin_command, job, plugin_execution_output_path)

    def execute_plugins(self, project, jobs, plugin_executions):
        # Prepare project (clone / pull)
        logger.info('Preparing project...')
        self.prepare_project(plugin_executions)

        logger.info('Generating bsub script...')
        commands = []
        for plugin_execution in plugin_executions:
            plugin_command = self.generate_plugin_execution_command(plugin_execution)
            jobs = Job.objects.filter(plugin_execution=plugin_execution).all()
            plugin_execution_output_path = os.path.join(self.log_path, str(plugin_execution.id))
            self.execute_command('mkdir %s' % plugin_execution_output_path, ignore_errors=True)

            for job in jobs:
                commands.append(self.generate_bsub_command(plugin_command, job, plugin_execution_output_path))

        logger.info('Sending and executing bsub script...')
        self.send_and_execute_file(commands, False)

    def get_plugin_execution_where_repository_url_is_set(self, plugin_executions):
        for plugin_execution in plugin_executions:
            if plugin_execution.repository_url is not None:
                return plugin_execution

        return None

    def prepare_project(self, plugin_executions):
        # As all plugin executions need to have the same repository url, we just look if we find a execution with a
        # set repository url
        found_plugin_execution = self.get_plugin_execution_where_repository_url_is_set(plugin_executions)

        if found_plugin_execution is not None:
            # Create project folder
            git_clone_target = os.path.join(self.project_path, found_plugin_execution.project.name)
            self.execute_command('rm -rf %s' % git_clone_target, ignore_errors=True)
            self.execute_command('git clone %s %s ' % (found_plugin_execution.repository_url, git_clone_target),
                                 ignore_errors=True)

    def delete_output_for_plugin_execution(self, plugin_execution):
        self.execute_command('rm -rf %s' % os.path.join(self.log_path, str(plugin_execution.id)))

    def get_output_log(self, job):
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10021) as handler:
            sftp_client = handler.get_ssh_client().open_sftp()
            plugin_execution_output_path = os.path.join(self.log_path, str(job.plugin_execution.id))
            try:
                remote_file = sftp_client.open(os.path.join(plugin_execution_output_path, str(job.id)+'_out.txt'))
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
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10022) as handler:
            sftp_client = handler.get_ssh_client().open_sftp()
            plugin_execution_output_path = os.path.join(self.log_path, str(job.plugin_execution.id))
            try:
                remote_file = sftp_client.open(os.path.join(plugin_execution_output_path, str(job.id)+'_err.txt'))
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
        plugin_execution_output_path = os.path.join(self.log_path, str(jobs[0].plugin_execution.id))
        for job in jobs:
            error_path = os.path.join(plugin_execution_output_path, str(job.id)+'_err.txt')
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
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10023) as handler:
            scp = SCPClient(handler.get_ssh_client().get_transport())

            # Copy plugin
            scp.put(plugin.get_full_path_to_archive(), remote_path=b'~')

        try:
            self.delete_plugin(plugin)
        except Exception:
            pass

        # Untar plugin
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
        path_to_execute_script = "%s/%s/execute.sh " % (self.plugin_path, str(plugin))

        # Make execution script executable
        self.execute_command("chmod +x %s" % path_to_install_script)
        self.execute_command("chmod +x %s" % path_to_execute_script)

        # Add parameters
        command = self.add_parameters_to_install_command(path_to_install_script, plugin)

        return string.Template(command).substitute({
            'plugin_path': os.path.join(self.plugin_path, str(plugin))
        })

    def add_parameters_to_install_command(self, path_to_script, plugin):
        command = path_to_script

        for argument in plugin.argument_set.all().filter(type='install').order_by('position'):
            # Add none if the value is not set, this needs to be catched in the install.sh of the plugin
            if not argument.install_value.strip():
                command += "None"
            else:
                command += argument.install_value+" "

        return command

    def execute_command(self, command, ignore_errors=False):

        logger.info('Execute command: %s' % command)

        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10024) as handler:
            (stdout, stderr) = handler.execute(command)

            logger.debug('Output: %s' % ' '.join(stdout))
            logger.debug('ErrorOut: %s' % ' '.join(stderr))
            if stderr and not ignore_errors:
                raise Exception('Error in executing command %s! Error: %s.' % (command, ','.join(stderr)))

        return stdout

    def send_and_execute_file(self, commands, blocking):
        generated_uuid = str(uuid.uuid4())
        path_to_sh_file = os.path.join(os.path.dirname(__file__), 'temp', generated_uuid+'.sh')
        path_to_remote_sh_file = os.path.join(self.project_path, generated_uuid+'.sh')
        with open(path_to_sh_file, 'w') as shell_file:
            shell_file.write("#!/bin/sh\n")

            for line in commands:
                shell_file.write("%s\n" % line)
            shell_file.write("rm -rf %s\n" % path_to_remote_sh_file)

        # Copy Shell file with jobs to execute
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10025) as handler:
            scp = SCPClient(handler.get_ssh_client().get_transport())
            scp.put(path_to_sh_file, remote_path=b'%s' % str.encode(path_to_remote_sh_file))

        # Delete local file
        subprocess.run(['rm', '-rf', path_to_sh_file])

        # Make remote file executable
        self.execute_command('chmod +x %s' % path_to_remote_sh_file)

        # Execute. We need the variable order_needed as it distighushes between two separate possible execution methods
        logger.info("Execute command: %s" % path_to_remote_sh_file)
        if blocking:
            with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                              self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10026) as handler:
                out = handler.execute_file(path_to_remote_sh_file, True)
                logger.debug('Output: %s' % ' '.join(out))
                return out
        else:
            thread = JobSubmissionThread(path_to_remote_sh_file, self.host, self.username, self.password, self.port,
                                         self.tunnel_host, self.tunnel_username, self.tunnel_password,self.tunnel_port,
                                         self.use_tunnel)
            thread.start()
            return None
