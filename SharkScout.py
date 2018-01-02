#!/usr/bin/env python3

import argparse
import atexit
import concurrent.futures
from datetime import date
import logging
import os
import psutil
import pynumparser
from tqdm import tqdm
import subprocess
import sys
import time
import webbrowser

import sharkscout


if __name__ == '__main__':
    # Clean up child processes on quit
    @atexit.register
    def goodbye():
        proc = psutil.Process()
        children = proc.children()
        for child in children:
            child.terminate()
        psutil.wait_procs(children, timeout=5)

    # Parse arguments
    def file_exists(path):
        if not os.path.exists(path):
            raise argparse.ArgumentTypeError(path + " does not exist")
        elif not os.path.isfile(path):
            raise argparse.ArgumentTypeError(path + " is not a file")
        return path
    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('-ut', '--update-teams', dest='update_teams', help='update TBA team list', action='store_true', default=False)
    parser.add_argument('-uti', '--update-teams-info', dest='update_teams_info', help='update TBA team info', action='store_true', default=False)
    parser.add_argument('-ue', '--update-events', metavar='year', dest='update_events', help='update all TBA events in a year', type=pynumparser.NumberSequence(limits=(1992, date.today().year+1)))
    parser.add_argument('-uei', '--update-events-info', metavar='year', dest='update_events_info', help='update all TBA event info in a year', type=pynumparser.NumberSequence(limits=(1992, date.today().year+1)))
    parser.add_argument('-d', '--dump', metavar='file', help='run mongodump after any update(s)', type=str)
    parser.add_argument('-r', '--restore', metavar='file', help='run mongorestore before any update(s)', type=file_exists)
    args = parser.parse_args()
    # Massage arguments
    args.update_events = list(args.update_events or [])
    args.update_events_info = list(args.update_events_info or [])

    # Logging
    logging.getLogger('backoff').addHandler(logging.StreamHandler())

    # Start MongoDB
    mongo = sharkscout.Mongo()
    mongo.index()

    # mongorestore
    build_restored = False
    if not args.restore and not mongo.tba_count:
        build_dump = os.path.join(os.path.dirname(__file__), 'mongodump.gz')
        if os.path.exists(build_dump):
            args.restore = build_dump
            build_restored = True
    if args.restore:
        print('Importing database from "' + args.restore + '" ...')
        null = open(os.devnull, 'w')
        subprocess.Popen([
            sharkscout.Util.which('mongorestore'),
            '/port', str(sharkscout.Mongo.port),
            '/gzip',
            '/archive:"' + args.restore + '"',
            '/objcheck'
        ], stdout=null, stderr=subprocess.STDOUT).wait()
        null.close()
        if build_restored:
            os.remove(args.restore)
        print()

    # Team updates
    if args.update_teams:
        print('Updating team list ...')
        mongo.teams_update()
        print()
    if args.update_teams_info:
        print('Updating team info ...')
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(mongo.team_update, team['key']): team for team in mongo.teams()}
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), unit='team', leave=True):
                pass
        print()

    # Event updates
    if args.update_events or args.update_events_info:
        for year in sorted(list(set(args.update_events + args.update_events_info))):
            if year in args.update_events:
                print('Updating ' + str(year) + ' event list ...')
                mongo.events_update(year)
            if year in args.update_events_info:
                print('Updating ' + str(year) + ' events ...')
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                    futures = {pool.submit(mongo.event_update, event['key']): event for event in mongo.events(year)}
                    for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), unit='event', leave=True):
                        pass
            print()

    # mongodump
    if args.dump:
        print('Dumping database to "' + args.dump + '" ...')
        null = open(os.devnull, 'w')
        subprocess.Popen([
            sharkscout.Util.which('mongodump'),
            '/port', str(sharkscout.Mongo.port),
            '/db', 'shark_scout',
            '/gzip',
            '/archive:"' + args.dump + '"'
        ], stdout=null, stderr=subprocess.STDOUT).wait()
        null.close()
        print()

    # Exit if updated anything
    if [a for a in dir(args) if a.startswith('update_') and getattr(args, a)]:
        sys.exit(0)

    # Open web server and run indefinitely
    web_server = sharkscout.WebServer()
    web_server.start()

    # Open the web browser
    while not web_server.running:
        time.sleep(0.1)
    webbrowser.open('http://127.0.0.1:' + str(web_server.port))
