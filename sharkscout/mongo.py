from datetime import date
import os
import pymongo
import pymongo.errors
import re
import subprocess
import sys

import sharkscout


class Mongo(object):
    def __init__(self):
        self.client = pymongo.MongoClient()

        self.shark_scout = self.client.shark_scout
        self.ss_scouting = self.shark_scout.scouting

        self.the_blue_alliance = self.client.the_blue_alliance
        self.tba_events = self.the_blue_alliance.events
        self.tba_teams = self.the_blue_alliance.teams

        self.tba_api = sharkscout.TheBlueAlliance()

    def start(self):
        if not sharkscout.Util.pid('mongod'):
            mongo_dir = os.path.join(os.path.dirname(sys.argv[0]), 'mongo')
            if not os.path.exists(mongo_dir):
                os.mkdir(mongo_dir)

            try:
                null = open(os.devnull, 'w')
                subprocess.Popen(['mongod', '--dbpath', mongo_dir, '--smallfiles'], stdout=null, stderr=subprocess.STDOUT)
            except FileNotFoundError:
                print('mongod couldn\'t start')
                sys.exit(1)

    # Ensure indexes on MongoDB
    def index(self):
        self.ss_scouting.create_index('event_key')
        self.ss_scouting.create_index([
            ('event_key', pymongo.ASCENDING),
            ('team_key', pymongo.ASCENDING)
        ], unique=True)
        self.tba_events.create_index('event_code')
        self.tba_events.create_index('key', unique=True)
        self.tba_events.create_index('teams')
        self.tba_events.create_index('year')
        self.tba_teams.create_index('key', unique=True)
        self.tba_teams.create_index('team_number', unique=True)

    # List of all events in a given year
    def events(self, year):
        return list(self.tba_events.find({'year': int(year)}).sort('start_date'))

    # List of all years with events, and all weeks in a given year
    def events_stats(self, year):
        return {
            'years': sorted(self.tba_events.distinct('year'), reverse=True),
            'weeks': sorted([w for w in self.tba_events.find({'year': int(year)}).distinct('week') if w is not None])
        }

    # Event information
    def event(self, event_key):
        event = list(self.tba_events.find({'key': event_key}))
        if event:
            event = event[0]
            # Get full team information
            if 'teams' in event:
                event['teams'] = self.teams_list(event['teams'])
                scouting = self.scouting_pit_teams(event_key)
                for team_idx, team in enumerate(event['teams']):
                    if team['key'] in scouting:
                        event['teams'][team_idx]['scouting'] = scouting[team['key']]
            # Infer missing match information from scouting information
            if 'matches' not in event:
                event.update({'matches': self.scouting_matches(event_key)})
            # Attach scouting data
            if 'matches' in event:
                scouting = self.scouting_matches_teams(event['key'])
                for match_idx, match in enumerate(event['matches']):
                    if match['key'] in scouting:
                        match['scouting'] = scouting[match['key']]
                    event['matches'][match_idx] = match
        return event

    # List of all events (years) with a given event code
    def event_years(self, event_code):
        return list(self.tba_events.find({'event_code': event_code}).sort('year', pymongo.DESCENDING))

    # TBA update the event listing for a year
    def events_update(self, year):
        events = self.tba_api.events(year)
        bulk = self.tba_events.initialize_unordered_bulk_op()
        # Upsert events
        for event in events:
            bulk.find({'key': event['key']}).upsert().update({'$set': event})
        # Delete events
        missing = [e['key'] for e in self.tba_events.find({
            'year': int(year),
            'key': {'$nin': [e['key'] for e in events]}
        })]
        bulk.find({'key': {'$in': missing}}).remove()
        # Execute
        try:
            bulk.execute()
        except pymongo.errors.InvalidOperation:
            pass  # "No operations to execute"

    # TBA update an individual event
    def event_update(self, event_key):
        event = self.tba_api.event(event_key)
        if event:
            event.update({k:v for k, v in {
                # Info that can be known before an event starts
                'teams': sorted([t['key'] for t in self.tba_api.event_teams(event_key)]),
                'matches': self.tba_api.event_matches(event_key),
                # Info that can't be known before an event starts
                'rankings': self.tba_api.event_rankings(event_key),
                'stats': self.tba_api.event_stats(event_key),
                'awards': self.tba_api.event_awards(event_key)
            }.items() if v})
            self.tba_events.update_one({'key': event['key']}, {'$set': event}, upsert=True)

    # List of matches with scouting data
    def scouting_matches(self, event_key):
        matches = list(self.ss_scouting.aggregate([{'$match': {
            'event_key': event_key
        }}, {'$unwind': {
            'path': '$matches'
        }}, {'$group': {
            '_id': '$matches.match_key',
            'team_keys': {'$addToSet': '$team_key'},
            'blue': {
                '$addToSet': {
                    '$cond': {
                        'if': {'$eq': ['$matches.team_color', 'blue']},
                        'then': '$team_key',
                        'else': None
                    }
                }
            },
            'red': {
                '$addToSet': {
                    '$cond': {
                        'if': {'$eq': ['$matches.team_color', 'red']},
                        'then': '$team_key',
                        'else': None
                    }
                }
            }
        }}, {'$project': {
            '_id': 0,
            'key': '$_id',
            'team_keys': '$team_keys',
            'alliances': {
                'blue': {
                    'teams': {'$setDifference': ['$blue', [None]]}
                },
                'red': {
                    'teams': {'$setDifference': ['$red', [None]]}
                }
            }
        }}]))

        comp_level_map = {
            'qm': 0,
            'ef': 1,
            'qf': 2,
            'sf': 3,
            'f': 4
        }
        for match_idx, match in enumerate(matches):
            match['event_key'] = event_key
            for alliance in match['alliances']:
                match['alliances'][alliance]['score'] = 0
                match['alliances'][alliance]['teams'] = sorted(match['alliances'][alliance]['teams'])
            # Parse match key into comp_level, match_number, set_number
            result = re.match(r'^[^_]+_([^0-9]+)([0-9]+)m?([0-9]+)?', match['key'])
            match['comp_level'] = result.group(1)
            match['match_number'] = int(result.group(2))
            if result.group(3) is not None:
                match['set_number'] = int(result.group(3))
            # Sort by: comp_level, match_number, set_number (in that order)
            sort = 0
            for group_idx, group in enumerate(list(result.groups())[::-1]):
                if group in comp_level_map:
                    group = comp_level_map[group]
                sort += int(group or 0) * (10 ** (3 * group_idx))
            matches[match_idx]['_sort'] = sort
        matches = sorted(matches, key=lambda v: v['_sort'])

        return matches

    # List of teams within matches with scouting data
    def scouting_matches_teams(self, event_key):
        return {m['key']: m['team_keys'] for m in self.scouting_matches(event_key)}

    def scouting_matches_raw(self, event_key):
        return list(self.ss_scouting.aggregate([{'$match': {
            'event_key': event_key
        }}, {'$unwind': {
            'path': '$matches'
        }}, {'$replaceRoot': {
            'newRoot': '$matches'
        }}]))

    # Return scouting data given an event key, match key, and team key
    def scouting_match(self, event_key, match_key, team_key):
        scouting = list(self.ss_scouting.aggregate([{'$match': {
            'event_key': event_key,
            'team_key': team_key
        }}, {'$project': {
            'matches': {
                '$filter': {
                    'input': '$matches',
                    'as': 'match',
                    'cond': {
                        '$eq': ['$$match.match_key', match_key]
                    }
                }
            }
        }}, {'$project': {
            'match': {
                '$arrayElemAt': ['$matches', 0]
            }
        }}, {'$match': {
            'match': {'$exists': True}
        }}]))
        if scouting:
            scouting = scouting[0]['match']
        return scouting

    # Upsert scouted data
    def scouting_match_update(self, data):
        # Update if existing
        result = self.ss_scouting.update_one({
            'event_key': data['event_key'],
            'team_key': data['team_key'],
            'matches.match_key': data['match_key']
        }, {'$set': {
            'matches.$': data
        }})
        if not result.matched_count:
            # Insert otherwise
            result = self.ss_scouting.update_one({
                'event_key': data['event_key'],
                'team_key': data['team_key'],
            }, {'$push': {
                'matches': data
            }}, upsert=True)
        return (result.upserted_id or result.matched_count or result.modified_count)

    def scouting_pit(self, event_key, team_key):
        scouting = list(self.ss_scouting.aggregate([{'$match': {
            'event_key': event_key,
            'team_key': team_key
        }}, {'$match': {
            'pit': {'$exists': True}
        }}, {'$replaceRoot': {
            'newRoot': '$pit'
        }}]))
        if scouting:
            scouting = scouting[0]
        return scouting

    def scouting_pit_teams(self, event_key):
        scouting = list(self.ss_scouting.aggregate([{'$match': {
            'event_key': event_key
        }}, {'$match': {
            'pit': {'$exists': True}
        }}, {'$replaceRoot': {
            'newRoot': '$pit'
        }}]))
        if scouting:
            scouting = {t['team_key']: t for t in scouting}
        return scouting

    def scouting_pit_update(self, data):
        result = self.ss_scouting.update_one({
            'event_key': data['event_key'],
            'team_key': data['team_key'],
        }, {'$set': {
            'pit': data
        }}, upsert=True)
        return (result.upserted_id or result.matched_count or result.modified_count)

    # List of all teams
    def teams(self):
        return list(self.tba_teams.find())

    # List of all teams, paged
    def teams_paged(self, page, limit=1000):
        min_num = int(page) * limit
        max_num = (int(page) + 1) * limit - 1
        return list(self.tba_teams.find({'team_number': {'$gte': min_num, '$lte': max_num}}))

    # List of teams, given a set of team keys
    def teams_list(self, team_keys):
        return list(self.tba_teams.find({'key': {'$in': team_keys}}).sort('team_number'))

    # Count, min, and max of all team numbers
    def teams_stats(self):
        stats = list(self.tba_teams.aggregate([{'$group': {
            '_id': '$id',
            'count': {'$sum': 1},
            'min': {'$min': '$team_number'},
            'max': {'$max': '$team_number'}
        }}]))
        if stats:
            return stats[0]
        return {
            'count': 0,
            'min': 0,
            'max': 0
        }

    # TBA update the team listing
    def teams_update(self):
        bulk = self.tba_teams.initialize_unordered_bulk_op()
        for team in self.tba_api.teams_all():
            bulk.find({'key': team['key']}).upsert().update({'$set': team})
        bulk.execute()

    # Team information
    def team(self, team_key, year=None):
        team = list(self.tba_teams.find({'key': team_key}))
        if team:
            team = team[0]
            team['events'] = self.team_events(team_key, year)
        return team

    # TBA update an individual team
    def team_update(self, team_key):
        team = self.tba_api.team(team_key)
        team.update({k:v for k, v in {
            'awards': self.tba_api.team_history_awards(team_key)
        }.items() if v})
        self.tba_teams.update_one({'key': team['key']}, {'$set': team}, upsert=True)

    # Years that a team competed
    def team_stats(self, team_key):
        return {
            'years': sorted(self.tba_events.find({'teams': team_key}).distinct('year'), reverse=True)
        }

    # Events a team is attending in a given year
    def team_events(self, team_key, year):
        # Query
        events = list(self.tba_events.find({'teams': team_key, 'year': int(year)}).sort('start_date'))

        for event_idx, event in enumerate(events):
            # Infer missing match information from scouting information
            if 'matches' not in event:
                event.update({'matches': self.scouting_matches(event['key'])})

            if 'matches' in event:
                # Filter matches
                event['matches'] = [m for m in event['matches'] if team_key in m['alliances']['red']['teams'] or team_key in m['alliances']['blue']['teams']]

                # Attach scouting data
                scouting = self.scouting_matches_teams(event['key'])
                for match_idx, match in enumerate(event['matches']):
                    if match['key'] in scouting:
                        match['scouting'] = scouting[match['key']]
                    event['matches'][match_idx] = match

            events[event_idx] = event

        return events

    # TBA update all events a team is attending in a given year
    def team_update_events(self, team_key, year):
        for event in self.tba_api.team_events(team_key, int(year)):
            self.event_update(event['key'])
