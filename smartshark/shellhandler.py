

import paramiko
import re
import time

class ShellHandler:

    def __init__(self, host, user, psw, port):
        self.host = host
        self.user = user
        self.psw = psw
        self.port = port

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(self.host, username=self.user, password=self.psw, port=self.port)

    def get_ssh_client(self):
        return self.ssh

    def execute(self, cmd, stderr_stdout_combined=False):
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
            ssh = self.get_ssh_client()
            channel = ssh.invoke_shell()
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





