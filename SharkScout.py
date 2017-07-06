#!/usr/bin/env python3

import argparse
import concurrent.futures
from datetime import date
import logging
import pynumparser
from tqdm import tqdm
import sys

import sharkscout


if __name__ == '__main__':
    # Parse arguments
    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('-ut', '--update-teams', dest='update_teams', help='update TBA team list', action='store_true', default=False)
    parser.add_argument('-uti', '--update-teams-info', dest='update_teams_info', help='update TBA team info', action='store_true', default=False)
    parser.add_argument('-ue', '--update-events', metavar='year', dest='update_events', help='update all TBA events in a year', type=pynumparser.NumberSequence(limits=(1992, date.today().year+1)))
    parser.add_argument('-uei', '--update-events-info', metavar='year', dest='update_events_info', help='update all TBA event info in a year', type=pynumparser.NumberSequence(limits=(1992, date.today().year+1)))
    args = parser.parse_args()
    # Massage arguments
    args.update_events = list(args.update_events or [])
    args.update_events_info = list(args.update_events_info or [])

    # Logging
    logging.getLogger('backoff').addHandler(logging.StreamHandler())

    # Initialize TBA API
    sharkscout.TheBlueAlliance('frc226:sharkscout:v0')
    # Start MongoDB
    mongo = sharkscout.Mongo()
    mongo.start()
    mongo.index()

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
    # Exit if updated anything
    if [a for a in dir(args) if a.startswith('update_') and getattr(args, a)]:
        sys.exit(0)

    # Open web server and run indefinitely
    web_server = sharkscout.WebServer()
    web_server.start()
