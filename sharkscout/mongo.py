import argparse
from datetime import datetime, date
import os
import pymongo
import pymongo.errors
import re
import subprocess
import sys

import hjson

import sharkscout


class TBACache(object):
    def __init__(self, collection):
        self.collection = collection

    def __getitem__(self, key):
        return list(self.collection.find({'endpoint':key}))[0]['modified']

    def __setitem__(self, key, value):
        self.collection.update_one({'endpoint':key}, {'$set':{
            'endpoint': key,
            'modified': value
        }}, upsert=True)

    def __delitem__(self, key):
        self.collection.remove({'endpoint':key})

    def __contains__(self, key):
        return len(list(self.collection.find({'endpoint':key})))


class Mongo(object):
    port = None
    client = None

    def __init__(self):
        if self.__class__.client is None:
            self.start()
        self.client = self.__class__.client

        self.shark_scout = self.client.shark_scout
        self.tba_events = self.shark_scout.tba_events
        self.tba_teams = self.shark_scout.tba_teams
        self.tba_cache = self.shark_scout.tba_cache
        self.scouting = self.shark_scout.scouting

        cache = TBACache(self.tba_cache)
        self.tba_api = sharkscout.TheBlueAlliance(cache)

    def start(self):
        # Build and create database path
        mongo_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'mongo')
        if not os.path.exists(mongo_dir):
            os.mkdir(mongo_dir)

        # Look for mongod already running with same database path
        mongo_pid = None
        parser = argparse.ArgumentParser()
        parser.add_argument('--port', type=int, default=27017)
        parser.add_argument('--dbpath', default=None)
        for pid in sharkscout.Util.pids('mongod'):
            known, _ = parser.parse_known_args(sharkscout.Util.pid_to_argv(pid))
            if known.dbpath and not os.path.isabs(known.dbpath):
                known.dbpath = os.path.join(sharkscout.Util.pid_to_cwd(pid), known.dbpath)
            if known.dbpath is not None and os.path.normpath(known.dbpath) == os.path.normpath(mongo_dir):
                mongo_pid = pid
                self.__class__.port = known.port
                print('mongod already running on port ' + str(self.__class__.port))
                break

        if not mongo_pid:
            self.__class__.port = sharkscout.Util.open_port(27017)
            try:
                null = open(os.devnull, 'w')
                mongod = sharkscout.Util.which('mongod')
                if mongod is None:
                    print('mongod not found')
                    sys.exit(1)
                subprocess.Popen([
                    mongod,
                    '--port', str(self.__class__.port),
                    '--dbpath', mongo_dir,
                    '--smallfiles'
                ], stdout=null, stderr=subprocess.STDOUT)
                print('mongod started on port ' + str(self.__class__.port))
            except FileNotFoundError:
                print('mongod couldn\'t start')
                sys.exit(1)

        self.__class__.client = pymongo.MongoClient('localhost', self.__class__.port)
        print()

    # Ensure indexes on MongoDB
    def index(self):
        self.scouting.create_index('event_key')
        self.scouting.create_index([
            ('event_key', pymongo.ASCENDING),
            ('team_key', pymongo.ASCENDING)
        ], unique=True)
        self.tba_events.create_index('event_code')
        self.tba_events.create_index('key', unique=True)
        self.tba_events.create_index('teams')
        self.tba_events.create_index([
            ('year', pymongo.ASCENDING),
            ('start_date', pymongo.ASCENDING)
        ])
        self.tba_teams.create_index('key', unique=True)
        self.tba_teams.create_index('team_number', unique=True)
        self.tba_cache.create_index('endpoint', unique=True)

    # Perform database migrations
    def migrate(self):
        ##### Addition of created_timestamp and modified_timestamp #####
        # TBA events
        self.tba_events.update({
            'modified_timestamp': {'$exists': False}
        }, {
            '$set': {'modified_timestamp': datetime.utcfromtimestamp(0)}
        }, multi=True)
        bulk = self.tba_events.initialize_unordered_bulk_op()
        for event in self.tba_events.find({'created_timestamp': {'$exists': False}}):
            bulk.find({'_id': event['_id']}).update({
                '$set': {'created_timestamp': event['modified_timestamp']}
            })
        try:
            bulk.execute()
        except pymongo.errors.InvalidOperation:
            pass  # "No operations to execute"
        # TBA teams
        self.tba_teams.update({
            'modified_timestamp': {'$exists': False}
        }, {
            '$set': {'modified_timestamp': datetime.utcfromtimestamp(0)}
        }, multi=True)
        bulk = self.tba_teams.initialize_unordered_bulk_op()
        for event in self.tba_teams.find({'created_timestamp': {'$exists': False}}):
            bulk.find({'_id': event['_id']}).update({
                '$set': {'created_timestamp': event['modified_timestamp']}
            })
        try:
            bulk.execute()
        except pymongo.errors.InvalidOperation:
            pass  # "No operations to execute"

    @property
    def version(self):
        return self.shark_scout.command('serverStatus')['version']

    @property
    def tba_count(self):
        # (not using collection.count() because it can incorrectly return 0)
        return len(list(self.tba_events.find())) + len(list(self.tba_teams.find()))

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
            if 'teams' not in event:
                event['teams'] = []

            # Infer missing team information from scouting information
            pit_scouting = self.scouting_pit_teams(event_key)
            event['teams'] = list(set(event['teams'] + list(pit_scouting.keys())))
            match_scouting = self.scouting_matches_teams(event['key'])
            event['teams'] = list(set(event['teams'] + [t for m in match_scouting.values() for t in m]))

            # Resolve team list to full team information
            event['teams'] = self.teams_list(event['teams'])

            # Attach scouting data to teams
            for team_idx, team in enumerate(event['teams']):
                if team['key'] in pit_scouting:
                    event['teams'][team_idx]['scouting'] = pit_scouting[team['key']]

            # Infer missing match information from scouting information
            if 'matches' not in event:
                event.update({'matches': self.scouting_matches(event_key)})
            # Attach scouting data to matches
            if 'matches' in event:
                for match_idx, match in enumerate(event['matches']):
                    if match['key'] in match_scouting:
                        match['scouting'] = match_scouting[match['key']]
                    event['matches'][match_idx] = match
            return event
        else:
            return {}

    # List of all events (years) with a given event code
    def event_years(self, event_code):
        return list(self.tba_events.find({'event_code': event_code}).sort('year', pymongo.DESCENDING))

    # TBA update the event listing for a year
    def events_update(self, year):
        events = self.tba_api.events(year)
        bulk = self.tba_events.initialize_unordered_bulk_op()
        # Upsert events
        for event in events:
            bulk.find({'key': event['key']}).upsert().update({
                '$set': event,
                '$setOnInsert': {
                    'modified_timestamp': datetime.utcfromtimestamp(0),
                    'created_timestamp': datetime.utcnow()
                }
            })
        # Delete events that no longer exist
        if events:
            missing = [e['key'] for e in self.tba_events.find({
                'year': int(year),
                'key': {'$nin': [e['key'] for e in events]}
            })]
            if missing:
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
            # Info that can be known before an event starts
            event.update({k:v for k, v in {
                'teams': sorted([t['key'] for t in self.tba_api.event_teams(event_key)]),
                'matches': self.tba_api.event_matches(event_key)
            }.items() if v})
            # Info that can't be known before an event starts
            if not event['start_date'] or datetime.strptime(event['start_date'],'%Y-%m-%d').date() <= date.today():
                event.update({k: v for k, v in {
                    'rankings': self.tba_api.event_rankings(event_key),
                    'stats': self.tba_api.event_oprs(event_key),
                    'awards': self.tba_api.event_awards(event_key),
                    'alliances': self.tba_api.event_alliances(event_key)
                }.items() if v})
        event['modified_timestamp'] = datetime.utcnow()
        self.tba_events.update_one({
            'key': event_key
        }, {
            '$set': event,
            '$setOnInsert': {'created_timestamp': datetime.utcnow()}
        }, upsert=True)

    # List of matches with scouting data
    def scouting_matches(self, event_key):
        matches = list(self.scouting.aggregate([{'$match': {
            'event_key': event_key
        }}, {'$unwind': {
            'path': '$matches'
        }}, {'$match': {  # sanity check
            'matches.match_key': {'$ne': ''}
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
            match_key_regex = re.compile('^[^_]+_([^0-9]+)([0-9]+)m?([0-9]+)?')
            result = re.match(match_key_regex, match['key'])
            if result is None:  # quietly accept poorly-formatted match keys
                match['key'] = match['event_key'] + '_qm0'
                result = re.match(match_key_regex, match['key'])
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
        return list(self.scouting.aggregate([{'$match': {
            'event_key': event_key
        }}, {'$unwind': {
            'path': '$matches'
        }}, {'$replaceRoot': {
            'newRoot': '$matches'
        }}, {'$sort': {
            'match_key': 1,
            'team_key': 1
        }}]))

    # Return scouting data given an event key, match key, and team key
    def scouting_match(self, event_key, match_key, team_key):
        scouting = list(self.scouting.aggregate([{'$match': {
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
        else:
            return {}

    # Upsert scouted data
    def scouting_match_update(self, data):
        # Update if existing
        result = self.scouting.update_one({
            'event_key': data['event_key'],
            'team_key': data['team_key'],
            'matches.match_key': data['match_key']
        }, {'$set': {
            'matches.$': data
        }})
        if not result.matched_count:
            # Insert otherwise
            result = self.scouting.update_one({
                'event_key': data['event_key'],
                'team_key': data['team_key'],
            }, {'$push': {
                'matches': data
            }}, upsert=True)
        return (result.upserted_id or result.matched_count or result.modified_count)

    def scouting_pit(self, event_key, team_key):
        scouting = list(self.scouting.aggregate([{'$match': {
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
        else:
            return {}

    def scouting_pit_teams(self, event_key):
        scouting = list(self.scouting.aggregate([{'$match': {
            'event_key': event_key
        }}, {'$match': {
            'pit': {'$exists': True}
        }}, {'$replaceRoot': {
            'newRoot': '$pit'
        }}, {'$sort': {
            'team_key': 1
        }}]))
        scouting = {t['team_key']: t for t in scouting}
        return scouting

    def scouting_pit_update(self, data):
        result = self.scouting.update_one({
            'event_key': data['event_key'],
            'team_key': data['team_key'],
        }, {'$set': {
            'pit': data
        }}, upsert=True)
        return (result.upserted_id or result.matched_count or result.modified_count)

    def scouting_stats(self, event_key, matches=0):
        event = self.event(event_key)
        year_json = os.path.join(os.path.dirname(sys.argv[0]), 'stats', str(event['year']) + '.json')
        if not os.path.exists(year_json):
            return {
                'individual': [],
                'scatter': []
            }
        with open(year_json, 'r') as f:
            year_stats = hjson.load(f)
            year_individual = year_stats
            year_scatter = {
                'axes': {},
                'dataset': {}
            }
            if isinstance(year_stats, dict):
                if 'individual' in year_stats:
                    year_individual = year_stats['individual']
                if 'scatter' in year_stats:
                    year_scatter = year_stats['scatter']

        aggregation = [
            # Get matches from TBA data (so they're in order)
            {'$match': {'key': event_key}},
            # Fill in missing match list
            {'$addFields': {'matches': {'$ifNull': ['$matches',
                [{
                    'key': {'$concat': ['$key', '_qm' + str(match_number)]},
                    'event_key': '$key'  # to allow $unwind:$matches
                } for match_number in range(250)]
                + [{
                    'key': {'$concat': ['$key', '_' + comp_level + str(match_number) + 'm' + str(set_number)]},
                    'event_key': '$key'  # to allow $unwind:$matches
                } for comp_level in ['ef', 'qf', 'sf', 'f'] for match_number in range(8) for set_number in range(3)]
            ]}}},
            {'$unwind': '$matches'},
            {'$replaceRoot': {'newRoot': '$matches'}},
            # Match to scouting information, return scouting data
            {'$lookup': {
                'from': 'scouting',
                'localField': 'event_key',
                'foreignField': 'event_key',
                'as': 'scouting'
            }},
            {'$match': {'scouting': {'$ne': []}}},  # any scouting data exists at all
            {'$unwind': '$scouting'},
            {'$addFields': {'scouting.matches': {'$ifNull': ['$scouting.matches', [{
                'match_key': {'$concat': ['$event_key', '_qm1']},
                'event_key': '$event_key'
            }]]}}},  # to allow $unwind
            {'$unwind': '$scouting.matches'},
            {'$redact': {'$cond': {
                'if': {'$eq': ['$key', '$scouting.matches.match_key']},
                'then': '$$DESCEND',
                'else': '$$PRUNE'
            }}},
            {'$project': {
                'team_key': '$scouting.team_key',
                'pit': '$scouting.pit',
                'match': '$scouting.matches'
            }},
            {'$group': {
                '_id': '$team_key',
                'pit': {'$first': '$pit'},
                'matches': {'$push': '$match'}
            }},
            # Add in team information
            {'$lookup': {
                'from': 'tba_teams',
                'localField': '_id',
                'foreignField': 'key',
                'as': 'team'
            }},
            {'$addFields': {
                'team': {'$arrayElemAt': ['$team', 0]}
            }},
            {'$group': {
                '_id': '$_id',
                'team': {'$first': '$team'},
                'pit': {'$first': '$pit'},
                'matches': {'$first': '$matches'}
            }},
            # Run statistics groupings
            {'$addFields': {
                'matches': {'$slice': [
                    '$matches',
                    0 if int(matches) >= 0 else int(matches),
                    abs(int(matches)) or 2147483647
                ]}
            }},
            {'$unwind': '$matches'}
        ]
        aggregation.extend(year_individual)
        aggregation.extend([
            {'$addFields': {
               '_team_number':  {'$ifNull': ['$_team_number', '$_id']}
            }},
            {'$sort': {
                '_team_number': 1,
                '_id': 1
            }}
        ])

        individual = list(self.tba_events.aggregate(aggregation))
        return {
            'individual': individual,
            'scatter': {
                'axes': year_scatter['axes'],
                'dataset': {t['_team_number']:{k:t[year_scatter['dataset'][k]] for k in year_scatter['dataset']} for t in individual}
            }
        }

    # List of all teams
    def teams(self):
        return list(self.tba_teams.find())

    # List of all teams, paged
    def teams_paged(self, page, limit=500):
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
        else:
            return {
                'count': 0,
                'min': 0,
                'max': 0
            }

    # TBA update the team listing
    def teams_update(self):
        teams = self.tba_api.teams_all()
        bulk = self.tba_teams.initialize_unordered_bulk_op()

        # Upsert teams
        for team in teams:
            bulk.find({'key': team['key']}).upsert().update({
                '$set': team,
                '$setOnInsert': {
                    'modified_timestamp': datetime.utcfromtimestamp(0),
                    'created_timestamp': datetime.utcnow()
                }
            })
        # Delete teams that no longer exist
        if teams:
            missing = [t['key'] for t in self.tba_teams.find({
                'key': {'$nin': [t['key'] for t in teams]}
            })]
            if missing:
                bulk.find({'key': {'$in': missing}}).remove()
        try:
            bulk.execute()
        except pymongo.errors.InvalidOperation:
            pass  # "No operations to execute"

    # Team information
    def team(self, team_key, year=None):
        team = list(self.tba_teams.find({'key': team_key}))
        if team:
            team = team[0]
            if year is not None:
                team['events'] = self.team_events(team_key, year)
            return team
        else:
            return {}

    # TBA update an individual team
    def team_update(self, team_key):
        team = self.tba_api.team(team_key)
        if team:
            team.update({k:v for k, v in {
                'awards': self.tba_api.team_history_awards(team_key),
                'districts': {str(d['year']): d for d in self.tba_api.team_districts(team_key)}
            }.items() if v})
        team['modified_timestamp'] = datetime.utcnow()
        self.tba_teams.update_one({
            'key': team_key
        }, {
            '$set': team,
            '$setOnInsert': {'created_timestamp': datetime.utcnow()}
        }, upsert=True)

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
