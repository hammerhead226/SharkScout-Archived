#!/usr/bin/env python3

import argparse

try:
    from pip import main as pipmain
except:
    from pip._internal import main as pipmain


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('command', type=str, choices=['install'], help='command')
    args = parser.parse_args()

    if args.command == 'install':
        pipmain([
            'install',
            'backoff',
            'cherrypy',
            'genshi',
            'hjson',
            'psutil',
            'pymongo',
            'pynumparser',
            'requests',
            'tqdm',
            'ws4py'
        ])
