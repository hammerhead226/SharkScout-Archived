#!/usr/bin/env python3

import atexit
import sys
import time

import argparse
import concurrent.futures
import logging
import os
import psutil
import pynumparser
import subprocess
import webbrowser
from datetime import date
from tqdm import tqdm

import sharkscout

if __name__ == '__main__':
    @atexit.register
    def goodbye():
        """Clean up child processes on quit.
        
        The primary purpose of this is to stop any local mongod instances started.
        """
        proc = psutil.Process()
        children = proc.children()
        for child in children:
            child.terminate()
        psutil.wait_procs(children, timeout=5)


    # Parse arguments
    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('-p', '--port', metavar='port', help='webserver port (default: 2260)', type=int, default=2260)
    parser.add_argument('-nb', '--no-browser', dest='browser', help='don\'t automatically open the web browser',
                        action='store_false', default=True)
    parser.add_argument('-ut', '--update-teams', dest='update_teams', help='update TBA team list', action='store_true',
                        default=False)
    parser.add_argument('-uti', '--update-teams-info', dest='update_teams_info', help='update TBA team info',
                        action='store_true', default=False)
    parser.add_argument('-utf', '--update-teams-favicon', dest='update_teams_favicon',
                        help='update team website\'s favicon when updating team info', action='store_true',
                        default=False)
    parser.add_argument('-ue', '--update-events', metavar='year', dest='update_events',
                        help='update all TBA events in a year',
                        type=pynumparser.NumberSequence(limits=(1992, date.today().year + 1)))
    parser.add_argument('-uei', '--update-events-info', metavar='year', dest='update_events_info',
                        help='update all TBA event info in a year',
                        type=pynumparser.NumberSequence(limits=(1992, date.today().year + 1)))
    parser.add_argument('-uef', '--update-events-favicon', dest='update_events_favicon',
                        help='update event website\'s favicon when updating event info', action='store_true',
                        default=False)
    parser.add_argument('-m', '--mongo', dest='mongo_host', help='mongo host URL', type=str)
    parser.add_argument('-d', '--dump', metavar='file', help='run mongodump after any update(s)', type=str)
    parser.add_argument('-r', '--restore', metavar='file', help='run mongorestore before any update(s)',
                        type=argparse.FileType('r'))
    args = parser.parse_args()
    # Massage arguments
    args.update_events = list(args.update_events or [])
    args.update_events_info = list(args.update_events_info or [])

    # Logging
    logging.getLogger('backoff').addHandler(logging.StreamHandler())

    # Start MongoDB
    mongo = sharkscout.Mongo(args.mongo_host)
    mongo.index()
    mongo.migrate()

    # mongorestore
    build_restored = False
    build_dump = os.path.join(os.path.dirname(__file__), 'mongodump.gz')
    if os.path.exists(build_dump):
        if not args.restore and not mongo.tba_count:
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
        print('Updating teams ...')
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(mongo.team_update, team['key'], args.update_teams_favicon): team for team in
                       mongo.teams()}
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), unit='team', leave=True):
                future.result()
        print()

    # Event updates
    if args.update_events:
        print('Updating event lists ...')
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(mongo.events_update, year): year for year in args.update_events}
            for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), unit='year', leave=True):
                future.result()
        print()
    if args.update_events_info:
        for year in sorted(args.update_events_info):
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                futures = {pool.submit(mongo.event_update, event['key'], args.update_events_favicon): event for event in
                           mongo.events(year)}
                if futures:
                    print('Updating ' + str(year) + ' events ...')
                    for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), unit='event',
                                       leave=True):
                        future.result()
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
    web_server = sharkscout.WebServer(args.port)
    web_server.start()

    # Open the web browser
    if args.browser:
        while not web_server.running:
            time.sleep(0.1)
        webbrowser.open('http://127.0.0.1:' + str(web_server.port))
