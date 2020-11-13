import paramiko
import re
import time

from paramiko import SSHException
from sshtunnel import SSHTunnelForwarder, HandlerSSHTunnelForwarderError


class ShellHandler:

    def __init__(self, host, user, psw, port, tunnel_host, tunnel_user, tunnel_psw, tunnel_port, use_tunnel,
                 bind_port=10020, key_path=None):
        self.host = host
        self.user = user
        self.psw = psw
        self.port = port
        self.tunnel_host = tunnel_host
        self.tunnel_user = tunnel_user
        self.tunnel_psw = tunnel_psw
        self.tunnel_port = tunnel_port
        self.use_tunnel = use_tunnel
        self.ssh = None
        self.server = None
        self.bind_port = bind_port
        self.key_path = key_path
        # self.p = paramiko.ecdsakey.ECDSAKey.from_private_key_file(key_path)
        self.p = paramiko.rsakey.RSAKey.from_private_key_file(key_path)

    def __enter__(self):
        if self.use_tunnel:
            timeout = 60
            timeout_start = time.time()
            not_connected = True

            while time.time() < timeout_start + timeout and not_connected is True:
                try:
                    self.server = SSHTunnelForwarder(
                        (self.tunnel_host, self.tunnel_port),
                        ssh_username=self.tunnel_user,
                        ssh_password=self.tunnel_psw,
                        remote_bind_address=(self.host, self.port),
                        local_bind_address=('127.0.0.1', self.bind_port)
                    )
                    self.server.start()

                    self.ssh = paramiko.SSHClient()
                    self.ssh.load_system_host_keys()
                    self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    # self.ssh.connect('127.0.0.1', self.bind_port, pkey=self.p)  # username=self.user, password=self.psw)
                    self.ssh.connect('127.0.0.1', self.bind_port, username=self.user)  # username=self.user, password=self.psw)
                    not_connected = False
                except (HandlerSSHTunnelForwarderError, SSHException) as e:
                    self.bind_port = self.bind_port + 1
        else:
            self.ssh = paramiko.SSHClient()
            self.ssh.load_system_host_keys()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            # self.ssh.connect(self.host, self.port, pkey=self.p)  # username=self.user, password=self.psw)
            self.ssh.connect(self.host, self.port, username=self.user, pkey=self.p)  # username=self.user, password=self.psw)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.use_tunnel:
            self.server.close()
        else:
            self.ssh.close()

        return

    def get_ssh_client(self):
        return self.ssh

    def execute(self, cmd):
        """

        :param cmd: the command to be executed on the remote computer
        :examples:  execute('ls')
                    execute('finger')
                    execute('cd folder_name')
        """
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        return stdout.readlines(), stderr.readlines()

    def execute_file(self, cmd, order_needed=False):
        if order_needed:
            tran = self.ssh.get_transport()
            chan = tran.open_session()
            chan.get_pty()
            out = chan.makefile()
            chan.exec_command(cmd)
            return out.readlines()
        else:
            channel = self.ssh.invoke_shell()
            stdin = channel.makefile('wb')
            stdout = channel.makefile('r')

            cmd = cmd.strip('\n')
            stdin.write(cmd + '\n')
            finish = 'end of stdOUT buffer. finished with exit status'
            echo_cmd = 'echo {} $?'.format(finish)
            stdin.write(echo_cmd + '\n')
            shin = stdin
            stdin.flush()

            shout = []
            sherr = []
            exit_status = 0

            for line in stdout:

                if str(line).startswith(cmd) or str(line).startswith(echo_cmd):
                    # up for now filled with shell junk from stdin
                    shout = []
                elif str(line).startswith(finish):
                    # our finish command ends with the exit status
                    exit_status = int(str(line).rsplit(maxsplit=1)[1])
                    if exit_status:
                        # stderr is combined with stdout.
                        # thus, swap sherr with shout in a case of failure.
                        sherr = shout
                        shout = []
                    break
                else:
                    # get rid of 'coloring and formatting' special characters
                    shout.append(re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]').sub('', line).
                                 replace('\b', '').replace('\r', ''))
            # first and last lines of shout/sherr contain a prompt
            if shout and echo_cmd in shout[-1]:
                shout.pop()
            if shout and cmd in shout[0]:
                shout.pop(0)
            if sherr and echo_cmd in sherr[-1]:
                sherr.pop()
            if sherr and cmd in sherr[0]:
                sherr.pop(0)

            return shout, sherr
