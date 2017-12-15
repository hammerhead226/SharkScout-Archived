import collections
import os
import psutil
import re
import socket
import string


class Util(object):
    @staticmethod
    def flatten(iterable):
        for item in iterable:
            if isinstance(item, collections.Iterable) and not isinstance(item, (str, bytes)):
                yield from Util.flatten(item)
            else:
                yield item

    @staticmethod
    def isnumeric(val):
        return str(val).lstrip('-').replace('.', '', 1).isdigit()

    @staticmethod
    def open_port(preferred=0):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('', preferred))
            port = sock.getsockname()[1]
        except OSError:
            port = Util.open_port()
        sock.close()
        return port

    @staticmethod
    def pid(bin):
        for proc in psutil.process_iter():
            try:
                if re.sub(r'\.[^\.]+$', r'', proc.name()) == bin:
                    return proc.pid
            except Exception as e:
                print(e)
        return 0

    @staticmethod
    def pids(bin):
        bin_pids = []
        for proc in psutil.process_iter():
            try:
                if re.sub(r'\.[^\.]+$', r'', proc.name()) == bin:
                    bin_pids.append(proc.pid)
            except Exception as e:
                print(e)
        return bin_pids

    @staticmethod
    def pid_of_port(port):
        for proc in psutil.process_iter():
            for conn in [c for c in proc.connections() if c.status == psutil.CONN_LISTEN]:
                if conn.laddr.port == port:
                    return proc.pid
        return 0

    @staticmethod
    def pid_to_argv(pid):
        proc = psutil.Process(pid)
        return proc.cmdline()

    @staticmethod
    def pid_to_cwd(pid):
        proc = psutil.Process(pid)
        return proc.cwd()

    @staticmethod
    def pid_to_path(pid):
        proc = psutil.Process(pid)
        return proc.exe()

    @staticmethod
    def which(bin):
        # Fast-search PATH first
        for path in os.environ['PATH'].split(os.pathsep):
            path = path.strip('"')
            if os.path.exists(path):
                for file in [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]:
                    if re.match(r'^' + bin + '(\.[^\.]+)?$', file):
                        return os.path.join(path, file)

        # Slow-search everywhere
        if os.name == 'nt':
            for drive in [d + ':\\' for d in string.ascii_uppercase]:
                if os.path.exists(drive):
                    for root, dirs, files in os.walk(drive):
                        for file in files:
                            if re.match(r'^' + bin + '(\.[^\.]+)?$', file):
                                return os.path.join(root, file)

        return None
