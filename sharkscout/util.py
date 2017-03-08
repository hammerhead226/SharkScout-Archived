import os
import psutil
import re


class Util(object):
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
    def which(bin):
        for path in os.environ['PATH'].split(os.pathsep):
            path = path.strip('"')
            if os.path.exists(path):
                for file in [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]:
                    if re.match(r'^' + bin + '(\.[^\.]+)?$', file):
                        return os.path.join(path, file)
        return None
