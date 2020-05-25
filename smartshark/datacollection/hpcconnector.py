import os
import re
import string
import subprocess
import threading
import uuid
import logging

from pycoshark.mongomodels import VCSSystem

from server.settings import HPC

from smartshark.utils.connector import BaseConnector
from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface
from smartshark.models import Job
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
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10020, self.ssh_key_path) as handler:
            out, err = handler.execute_file(self.remote_file, False)
            logger.debug(out)
            logger.debug(err)


class HPCConnector(PluginManagementInterface, BaseConnector):
    """
    Connector for the HPC cluster of the GWDG.

    plugins are installed to: root_path/plugins/<plugin_name>_<plugin_version>
    projects are cloned to: root_path/projects/<project_name>
    logs are saved to: log_path/<job_id>(_out|_err).txt


    """
    def __init__(self):
        super(HPCConnector, self).__init__()
        self.username = HPC['username']
        self.password = HPC['password']
        self.host = HPC['host']
        self.port = HPC['port']
        self.queue = HPC['queue']
        self.hosts_per_job = HPC['hosts_per_job']
        self.plugin_path = os.path.join(HPC['root_path'], 'plugins')
        self.project_path = os.path.join(HPC['root_path'], 'projects')
        self.log_path = HPC['log_path']
        self.tunnel_username = HPC['ssh_tunnel_username']
        self.tunnel_password = HPC['ssh_tunnel_password']
        self.tunnel_host = HPC['ssh_tunnel_host']
        self.tunnel_port = HPC['ssh_tunnel_port']
        self.use_tunnel = HPC['ssh_use_tunnel']
        self.cores_per_job = HPC['cores_per_job']
        self.local_log_path = HPC['local_log_path']
        self.ssh_key_path = HPC['ssh_key_path']

    @property
    def identifier(self):
        return 'GWDG'

    def default_queue(self):
        return self.queue

    def default_cores_per_job(self):
        return self.cores_per_job

    def generate_bsub_command(self, plugin_command, job, plugin_execution_output_path):
        output_path = os.path.join(plugin_execution_output_path, str(job.id) + '_out.txt')
        error_path = os.path.join(plugin_execution_output_path, str(job.id) + '_err.txt')

        cores_per_job = self.cores_per_job
        queue = self.queue

        # plugin execution may want to override some settings
        if job.plugin_execution.cores_per_job:
            cores_per_job = job.plugin_execution.cores_per_job
        if job.plugin_execution.queue:
            queue = job.plugin_execution.queue

        # bsub_command = 'bsub -n %s -W 48:00 -q %s -o %s -e %s -J "%s" ' % (cores_per_job, queue, output_path, error_path, job.id)
        bsub_command = '/opt/slurm/bin/sbatch -n %s -t 2-00:00:00 -p %s -o %s -e %s -N %s -J "%s" ' % (cores_per_job, queue, output_path, error_path, self.hosts_per_job, job.id)

        # required jobs no longer used
        # req_jobs = job.requires.all()
        # if req_jobs:
        #     bsub_command += "-w '"
        #     for req_job in req_jobs:
        #         bsub_command += 'ended("%s") && ' % str(req_job.id)

        #     bsub_command = bsub_command[:-4]
        #     bsub_command += "' "

        command = string.Template(plugin_command).safe_substitute({
            'path': os.path.join(self.project_path, job.plugin_execution.project.name),
            'revision': job.revision_hash
        })

        full_cmd = "%s%s" % (bsub_command, command)
        logger.debug('Generated bsub command: %s' % full_cmd)

        return full_cmd

    def get_sent_bash_command(self, job):
        plugin_command = self._generate_plugin_execution_command(self.plugin_path, job.plugin_execution)
        plugin_execution_output_path = os.path.join(self.log_path, str(job.plugin_execution.id))
        return self.generate_bsub_command(plugin_command, job, plugin_execution_output_path)

    def execute_plugins(self, project, plugin_executions):
        # Prepare project (clone / pull)
        logger.info('Preparing project...')
        self.prepare_project(plugin_executions)

        logger.info('Generating bsub script...')
        commands = []
        for plugin_execution in plugin_executions:
            plugin_command = self._generate_plugin_execution_command(self.plugin_path, plugin_execution)

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

        # TODO: Fails on multiple repositories for one project in the same plugin_execution list
        # Check if vcsshark is executed
        found_plugin_execution = self.get_plugin_execution_where_repository_url_is_set(plugin_executions)
        project_folder = os.path.join(self.project_path, found_plugin_execution.project.name)
        if any('vcsshark' == plugin_exec.plugin.name.lower() for plugin_exec in plugin_executions):
            # Create project folder
            logger.info('vcsshark is executed, remove old dir and clone new')
            self.execute_command('rm -rf %s' % project_folder, ignore_errors=True)
            self.execute_command('git clone %s %s ' % (found_plugin_execution.repository_url, project_folder),
                                 ignore_errors=True)
        else:
            # If there is a plugin that needs the repository folder and it is not existent,
            # we need to get it from the gridfs
            if found_plugin_execution is not None and not os.path.isdir(project_folder):
                logger.info('local project {} does not exist, fetching project from gridfs'.format(project_folder))
                repository = VCSSystem.objects.get(url=found_plugin_execution.repository_url).repository_file

                if repository.grid_id is None:
                    logger.error("Execute vcsshark first!")
                    raise Exception("VCSShark need to be executed first!")

                # Read tar_gz and copy it to temporary file
                tmp_tar_gz = 'tmp.tar.gz'
                with open(tmp_tar_gz, 'wb') as repository_tar_gz:
                    repository_tar_gz.write(repository.read())

                # Copy and extract tar on HPC system
                self.copy_project_tar()

                # Delete temporary tar_gz
                os.remove(tmp_tar_gz)


    def delete_output_for_plugin_execution(self, plugin_execution):
        self.execute_command('rm -rf %s' % os.path.join(self.log_path, str(plugin_execution.id)))

    def get_output_log(self, job):
        if self.local_log_path:
            return self._get_log_local(job, log_type='out')
        else:
            return self._get_output_log_ssh(job)

    def get_error_log(self, job):
        if self.local_log_path:
            return self._get_log_local(job, log_type='err')
        else:
            return self._get_error_log_ssh(job)

    def _get_log_local(self, job, log_type='out'):
        output = []

        file_path = os.path.join(self.local_log_path, str(job.plugin_execution.id), str(job.id) + '_' + log_type + '.txt')

        with open(file_path, 'r') as f:
            output = [line.strip() for line in f.readlines()]

        return output

    def _get_output_log_ssh(self, job):
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10021, self.ssh_key_path) as handler:
            sftp_client = handler.get_ssh_client().open_sftp()
            plugin_execution_output_path = os.path.join(self.log_path, str(job.plugin_execution.id))
            try:
                remote_file = sftp_client.open(os.path.join(plugin_execution_output_path, str(job.id) + '_out.txt'))
            except FileNotFoundError:
                return ['File Not Found']

            output = []
            try:
                for line in remote_file:
                    output.append(line.strip())
            finally:
                remote_file.close()

        return output

    def _get_error_log_ssh(self, job):
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10022, self.ssh_key_path) as handler:
            sftp_client = handler.get_ssh_client().open_sftp()
            plugin_execution_output_path = os.path.join(self.log_path, str(job.plugin_execution.id))
            try:
                remote_file = sftp_client.open(os.path.join(plugin_execution_output_path, str(job.id) + '_err.txt'))
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
        """Use slurms sacct to fetch the job status for the given list of jobs.

        possible formats and job states: https://slurm.schedmd.com/sacct.html
        """
        results = []
        job_ids = [str(job.id) for job in jobs]

        # 1. create job id batches
        for start in range(0, len(job_ids), 3000):
            chunk = job_ids[start:start + 3000]
            command = '/opt/slurm/bin/sacct -S 2019-01-01 --name {} --format="JobName,State"'.format(','.join(chunk))
            stdout = self.execute_command(command)

            states = {}
            for line in stdout[1:]:
                m = list(re.findall(r'\S+', line))  # split on any number of consecutive whitespaces
                if len(m) == 2:
                    states[m[0]] = m[1]

            for jid in chunk:
                if jid not in states.keys():
                    results.append('WAIT')
                elif states[jid].lower() == 'completed':
                    results.append('DONE')
                elif states[jid].lower() in ['pending', 'running', 'requeued', 'resizing', 'suspended']:
                    results.append('WAIT')
                else:
                    results.append('EXIT')

        return results

    # old lsf style
    # def get_job_stati(self, jobs):
    #     old lsf style
    #     if self.local_log_path:
    #         return self._get_job_stati_local(jobs)
    #     else:
    #         return self._get_job_stati_ssh(jobs)

    # old lsf style
    # def _get_job_stati_local(self, jobs):
    #     if not jobs:
    #         return []

    #     job_status_list = []
    #     plugin_execution_output_path = os.path.join(self.local_log_path, str(jobs[0].plugin_execution.id))

    #     for job in jobs:
    #         error_path = os.path.join(plugin_execution_output_path, str(job.id) + '_err.txt')
    #         out_path = os.path.join(plugin_execution_output_path, str(job.id) + '_out.txt')

    #         # file not present, job is not finished
    #         if not os.path.isfile(out_path) or not os.path.isfile(error_path):
    #             job_status_list.append('WAIT')
    #             continue

    #         # we have error logs something is wrong
    #         if os.path.getsize(error_path) > 0:
    #             job_status_list.append('EXIT')
    #             continue

    #         # last, we check the state
    #         try:
    #             with open(out_path, 'r') as f:
    #                 head = [next(f) for x in range(2)]

    #             # either we are Done or otherwise killed
    #             if head[1].strip().endswith(' Done'):
    #                 job_status_list.append('DONE')
    #             else:
    #                 job_status_list.append('EXIT')

    #         # this happens if we do not have 2 lines in the file
    #         except StopIteration:
    #             job_status_list.append('EXIT')

    #     return job_status_list

    # def _get_job_stati_ssh(self, jobs):
    #     if not jobs:
    #         return []

    #     job_status_list = []
    #     commands = []
    #     plugin_execution_output_path = os.path.join(self.log_path, str(jobs[0].plugin_execution.id))
    #     for job in jobs:
    #         error_path = os.path.join(plugin_execution_output_path, str(job.id) + '_err.txt')
    #         commands.append("wc -c < %s" % error_path)

    #     out = self.send_and_execute_file(commands, True)
    #     logger.debug(out)
    #     for out_line in out:
    #         out_line = out_line.strip()
    #         if out_line == '0':
    #             job_status_list.append('DONE')
    #         elif 'No such file or directory' in out_line:
    #             job_status_list.append('WAIT')
    #         else:
    #             job_status_list.append('EXIT')

    #     logger.debug(job_status_list)
    #     return job_status_list

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
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10023, self.ssh_key_path) as handler:
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

    def copy_project_tar(self):
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10023, self.ssh_key_path) as handler:
            scp = SCPClient(handler.get_ssh_client().get_transport())

            # Copy plugin
            scp.put('tmp.tar.gz', remote_path=b'~')

        # Untar plugin
        self.execute_command('mkdir -p %s' % self.project_path)
        self.execute_command('tar -C %s -xvf ~/tmp.tar.gz' % self.project_path)

        # Delete tar
        self.execute_command('rm -f ~/tmp.tar.gz')

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
        command = self._add_parameters_to_install_command(path_to_install_script, plugin)

        return string.Template(command).substitute({
            'plugin_path': os.path.join(self.plugin_path, str(plugin))
        })

    def execute_command(self, command, ignore_errors=False):

        logger.info('Execute command: %s' % command)

        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10024, self.ssh_key_path) as handler:
            (stdout, stderr) = handler.execute(command)

            logger.debug('Output: %s' % ' '.join(stdout))
            logger.debug('ErrorOut: %s' % ' '.join(stderr))
            if stderr and not ignore_errors:
                raise Exception('Error in executing command %s! Error: %s.' % (command, ','.join(stderr)))

        return stdout

    def send_and_execute_file(self, commands, blocking):
        generated_uuid = str(uuid.uuid4())
        path_to_sh_file = os.path.join(os.path.dirname(__file__), 'temp', generated_uuid + '.sh')
        path_to_remote_sh_file = os.path.join(self.project_path, generated_uuid + '.sh')
        with open(path_to_sh_file, 'w') as shell_file:
            shell_file.write("#!/bin/sh\n")

            for line in commands:
                shell_file.write("%s\n" % line)
            shell_file.write("rm -rf %s\n" % path_to_remote_sh_file)

        # Copy Shell file with jobs to execute
        with ShellHandler(self.host, self.username, self.password, self.port, self.tunnel_host,
                          self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10025, self.ssh_key_path) as handler:
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
                              self.tunnel_username, self.tunnel_password, self.tunnel_port, self.use_tunnel, 10026, self.ssh_key_path) as handler:
                out = handler.execute_file(path_to_remote_sh_file, True)
                logger.debug('Output: %s' % ' '.join(out))
                return out
        else:
            thread = JobSubmissionThread(path_to_remote_sh_file, self.host, self.username, self.password, self.port,
                                         self.tunnel_host, self.tunnel_username, self.tunnel_password, self.tunnel_port,
                                         self.use_tunnel)
            thread.start()
            return None
