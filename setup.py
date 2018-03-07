#!/usr/bin/env python3

import argparse
import pip


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('command', type=str, choices=['install'], help='command')
    args = parser.parse_args()

    if args.command == 'install':
        pip.main([
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
