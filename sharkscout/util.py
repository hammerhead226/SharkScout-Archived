import base64
import collections
import os
import psutil
import re
import requests
import socket
import string
import urllib.parse


class Util(object):
    """ """
    @staticmethod
    def favicon(url):
        """

        :param url:

        """
        if url:
            try:
                response = requests.get('https://www.google.com/s2/favicons', {'domain': url}, stream=True)
                image = base64.b64encode(response.raw.read()).decode()
                if image not in [
                    'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABHNCSVQICAgIfAhkiAAAABJJREFUOI1jYBgFo2AUjAIIAAAEEA'
                    'ABf014jgAAAABJRU5ErkJggg=='  # transparent 16x16 PNG
                ]:
                    return 'data:' + response.headers['Content-Type'] + ';base64,' + image
            except:
                pass
        return None

    @staticmethod
    def flatten(iterable):
        """

        :param iterable:

        """
        for item in iterable:
            if isinstance(item, collections.Iterable) and not isinstance(item, (str, bytes)):
                yield from Util.flatten(item)
            else:
                yield item

    @staticmethod
    def isnumeric(val):
        """

        :param val:

        """
        return str(val).lstrip('-').replace('.', '', 1).isdigit()

    @staticmethod
    def open_port(preferred=0):
        """

        :param preferred:  (Default value = 0)

        """
        # Check for other processes listening on the port
        if preferred and not Util.pid_of_port(preferred):
            return preferred

        # Let the system choose a random port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    @staticmethod
    def pid(name):
        """

        :param name:

        """
        for proc in psutil.process_iter():
            try:
                if re.sub(r'\.[^.]+$', r'', proc.name()) == name:
                    return proc.pid
            except Exception as e:
                print(e)
        return 0

    @staticmethod
    def pids(name):
        """

        :param name:

        """
        bin_pids = []
        for proc in psutil.process_iter():
            try:
                if re.sub(r'\.[^.]+$', r'', proc.name()) == name:
                    bin_pids.append(proc.pid)
            except Exception as e:
                print(e)
        return bin_pids

    @staticmethod
    def pid_of_port(port):
        """

        :param port:

        """
        for proc in psutil.process_iter():
            for conn in [c for c in proc.connections() if c.status == psutil.CONN_LISTEN]:
                if conn.laddr.port == port:
                    return proc.pid
        return 0

    @staticmethod
    def pid_ports(pid):
        """

        :param pid:

        """
        try:
            proc = psutil.Process(pid)
            return [c.laddr.port for c in proc.connections() if c.status == psutil.CONN_LISTEN]
        except psutil.NoSuchProcess:
            return []

    @staticmethod
    def pid_tree_ports(pid):
        """

        :param pid:

        """
        try:
            proc = psutil.Process(pid)
            ports = [c.laddr.port for c in proc.connections() if c.status == psutil.CONN_LISTEN]
            for child in proc.children(True):
                ports += [c.laddr.port for c in child.connections() if c.status == psutil.CONN_LISTEN]
            return ports
        except psutil.NoSuchProcess:
            return []

    @staticmethod
    def pid_to_argv(pid):
        """

        :param pid:

        """
        proc = psutil.Process(pid)
        return proc.cmdline()

    @staticmethod
    def pid_to_cwd(pid):
        """

        :param pid:

        """
        proc = psutil.Process(pid)
        return proc.cwd()

    @staticmethod
    def pid_to_path(pid):
        """

        :param pid:

        """
        proc = psutil.Process(pid)
        return proc.exe()

    @staticmethod
    def urlparse(url):
        """

        :param url:

        """
        if '//' not in url:
            url = '//' + url
        return urllib.parse.urlparse(url)

    @staticmethod
    def which(name):
        """

        :param name:

        """
        # Fast-search PATH first
        for path in os.environ['PATH'].split(os.pathsep):
            path = path.strip('"')
            if os.path.exists(path):
                for file in [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]:
                    if re.match(r'^' + name + '(\.[^.]+)?$', file):
                        return os.path.join(path, file)

        # Slow-search everywhere
        if os.name == 'nt':
            for drive in [d + ':\\' for d in string.ascii_uppercase]:
                if os.path.exists(drive):
                    for root, dirs, files in os.walk(drive):
                        for file in files:
                            if re.match(r'^' + name + '(\.[^.]+)?$', file):
                                return os.path.join(root, file)

        return None
