import sys

import argparse
import hjson
import os
import pymongo
import pymongo.errors
import re
import subprocess
from datetime import datetime, date

import sharkscout


class TBACache(object):
    def __init__(self, collection):
        """Dict-like class that uses mongo for hard storage.

        :param collection: mongo collection to use for storage
        :type collection: pymongo.collection.Collection
        """
        self.collection = collection

    def __getitem__(self, key):
        return list(self.collection.find({'endpoint': key}))[0]['modified']

    def __setitem__(self, key, value):
        self.collection.update_one({'endpoint': key}, {'$set': {
            'endpoint': key,
            'modified': value
        }}, upsert=True)

    def __delitem__(self, key):
        self.collection.remove({'endpoint': key})

    def __contains__(self, key):
        return len(list(self.collection.find({'endpoint': key})))


class Mongo(object):
    client = None

    def __init__(self, host=None):
        """Class to wrap all mongo database functionality.

        :param host: RFC 1808 & 3986 URL for mongo
        :type host: int, None
        """
        self.host = host

        if self.__class__.client is None:
            self.connect()
        self.client = self.__class__.client

        self.shark_scout = self.client.shark_scout
        self.tba_events = self.shark_scout.tba_events
        self.tba_teams = self.shark_scout.tba_teams
        self.tba_cache = self.shark_scout.tba_cache
        self.scouting = self.shark_scout.scouting

        cache = TBACache(self.tba_cache)
        self.tba_api = sharkscout.TheBlueAlliance(cache)

    def connect(self):
        """Connect to the mongo instance."""
        # Build and create database path
        mongo_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'mongo')
        if not os.path.exists(mongo_dir):
            os.mkdir(mongo_dir)

        # Use host from CLI params
        if self.host:
            host = sharkscout.Util.urlparse(self.host)
            if not host.hostname:
                print('invalid mongod host: ' + self.host)
                print()
                sys.exit(1)
            self.__class__.client = pymongo.MongoClient(host.hostname, host.port or 27017)
            print('mongod already running remotely at ' + self.host)
            print()
            return

        # Look for mongod already running locally with same database path
        parser = argparse.ArgumentParser()
        parser.add_argument('--port', type=int, default=27017)
        parser.add_argument('--dbpath', default=None)
        for pid in sharkscout.Util.pids('mongod'):
            known, _ = parser.parse_known_args(sharkscout.Util.pid_to_argv(pid))
            if known.dbpath and not os.path.isabs(known.dbpath):
                known.dbpath = os.path.join(sharkscout.Util.pid_to_cwd(pid), known.dbpath)
            if known.dbpath is not None and os.path.normpath(known.dbpath) == os.path.normpath(mongo_dir):
                self.__class__.client = pymongo.MongoClient('localhost', known.port)
                print('mongod already running on local port ' + str(known.port))
                print()
                return

        # Start mongod locally
        port = sharkscout.Util.open_port(27017)
        try:
            null = open(os.devnull, 'w')
            mongod = sharkscout.Util.which('mongod')
            if mongod is None:
                print('mongod not found locally')
                print()
                sys.exit(1)
            subprocess.Popen([
                mongod,
                '--port', str(port),
                '--dbpath', mongo_dir,
                '--smallfiles'
            ], stdout=null, stderr=subprocess.STDOUT)
            self.__class__.client = pymongo.MongoClient('localhost', port)
            print('mongod started on local port ' + str(port))
            print()
            return
        except FileNotFoundError:
            print('mongod couldn\'t start')
            print()
            sys.exit(1)

    def index(self):
        """Ensure indexes on MongoDB."""
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
            ('start_date', pymongo.ASCENDING),
            ('district.abbreviation', pymongo.ASCENDING),
            ('name', pymongo.ASCENDING)
        ])
        self.tba_teams.create_index('key', unique=True)
        self.tba_teams.create_index('team_number', unique=True)
        self.tba_cache.create_index('endpoint', unique=True)

    def migrate(self):
        """Perform database migrations."""
        # ----- Addition of created_timestamp and modified_timestamp -----
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
        """Return connected mongo instance's version.

        :rtype string
        """
        return self.shark_scout.command('serverStatus')['version']

    @property
    def tba_count(self):
        """Count of all TBA events + TBA teams.

        This is to detect the presence of any stored TBA data.

        :rtype int
        """
        # (not using collection.count() because it can incorrectly return 0)
        return len(list(self.tba_events.find())) + len(list(self.tba_teams.find()))

    def events(self, year):
        """List of all events in a given year.

        :param year: year to query events with
        :type year: int, string

        :rtype list
        """
        return list(self.tba_events.find({
            'year': int(year)
        }).sort([
            ('start_date', pymongo.ASCENDING),
            ('district.abbreviation', pymongo.ASCENDING),
            ('name', pymongo.ASCENDING)
        ]))

    def events_stats(self, year):
        """List of all years with events, and all weeks in a given year.

        :param year: year to query event weeks with
        :type year: int, string

        :rtype dict
        """
        return {
            'years': sorted(self.tba_events.distinct('year'), reverse=True),
            'weeks': sorted([w for w in self.tba_events.find({'year': int(year)}).distinct('week') if w is not None])
        }

    def event(self, event_key):
        """Event information.

        :param event_key: event key to query with]
        :type event_key: string

        :rtype dict
        """
        event = list(self.tba_events.find({'key': event_key}))
        if event:
            event = event[0]
            if 'teams' not in event:
                event['teams'] = []

            # Infer missing team information from scouting information
            scouting_pit = self.scouting_pit_teams(event_key)
            event['teams'] = list(set(event['teams'] + list(scouting_pit.keys())))
            scouting_match_teams = self.scouting_matches_teams(event['key'])
            event['teams'] = list(set(event['teams'] + [t for m in scouting_match_teams.values() for t in m]))

            # Resolve team list to full team information
            event['teams'] = self.teams_list(event['teams'])

            # Attach scouting data to teams
            for team_idx, team in enumerate(event['teams']):
                if team['key'] in scouting_pit:
                    event['teams'][team_idx]['scouting'] = scouting_pit[team['key']]

            # Infer missing match information from scouting information
            scouting_matches = {m['key']: m for m in self.scouting_matches(event_key)}
            if 'matches' not in event or not event['matches']:
                event['matches'] = list(scouting_matches.values())
            if 'matches' in event:
                for match_idx, match in enumerate(event['matches']):
                    # Add teams to alliance list from scouting data
                    for alliance in match['alliances']:
                        if match['key'] in scouting_matches and alliance in scouting_matches[match['key']]['alliances']:
                            if 'team_keys' in match['alliances'][alliance]:
                                match['alliances'][alliance]['team_keys'] += \
                                    [t for t in scouting_matches[match['key']]['alliances'][alliance]['teams']
                                     if t not in match['alliances'][alliance]['team_keys']]
                            if 'teams' in match['alliances'][alliance]:
                                match['alliances'][alliance]['teams'] += \
                                    [t for t in scouting_matches[match['key']]['alliances'][alliance]['teams']
                                     if t not in match['alliances'][alliance]['teams']]
                    # Attach scouting data to matches
                    if match['key'] in scouting_match_teams:
                        match['scouting'] = scouting_match_teams[match['key']]
                    event['matches'][match_idx] = match
            return event
        else:
            return {}

    def event_years(self, event_code):
        """List of all events (years) with a given event code.

        :param event_code: event code to query with
        :type event_code: string

        :rtype list
        """
        return list(self.tba_events.find({'event_code': event_code}).sort('year', pymongo.DESCENDING))

    def events_update(self, year):
        """TBA update the event listing for a year.

        :param year: year to update events for
        :type year: int, string
        """
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

    def event_update(self, event_key, update_favicon=False):
        """TBA update an individual event.

        :param event_key: event to update
        :param update_favicon: download the favicon or not (Default value = False)
        :type event_key: string
        :type update_favicon: bool
        """
        event = self.tba_api.event(event_key, True)
        if event:
            # Info that can be known before an event starts
            event.update({k: v for k, v in {
                'teams': sorted([t['key'] for t in self.tba_api.event_teams(event_key)]),
                'matches': self.tba_api.event_matches(event_key),
                'favicon': sharkscout.Util.favicon(
                    event['website'] if 'website' in event else '') if update_favicon else None
            }.items() if v})
            # Info that can't be known before an event starts
            if not event['start_date'] or datetime.strptime(event['start_date'], '%Y-%m-%d').date() <= date.today():
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

    def scouting_matches(self, event_key):
        """List of matches with scouting data.

        :param event_key: event key to query with
        :type event_key: string

        :rtype list
        """
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

    def scouting_matches_teams(self, event_key):
        """List of teams within matches with scouting data.

        :param event_key: event key to query with
        :type event_key: string

        :rtype dict
        """
        return {m['key']: m['team_keys'] for m in self.scouting_matches(event_key)}

    def scouting_matches_raw(self, event_key):
        """Return match scouting data for an event.

        :param event_key: event key to query with
        :type event_key: string

        :rtype list
        """
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

    def scouting_match(self, event_key, match_key, team_key):
        """Return match scouting data given an event key, match key, and team key.

        :param event_key: event key to query with
        :param team_key: team key to query with
        :param match_key: match key to query with
        :type event_key: string
        :type team_key: string
        :type match_key: string

        :rtype dict
        """
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

    def scouting_match_update(self, data):
        """Upsert match scouting data.

        :param data: scouting data to save
        :type data: dict

        :rtype bool
        """
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
        return result.upserted_id or result.matched_count or result.modified_count

    def scouting_pit(self, event_key, team_key):
        """Return pit scouting data for a team at an event.

        :param event_key: event key to query with
        :param team_key: team key to query with
        :type event_key: string
        :type team_key: string

        :rtype dict
        """
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
        """Return pit scouting data for all teams at an event.

        :param event_key: event key to query with
        :type event_key: string

        :rtype dict
        """
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
        """Upsert pit scouting data.

        :param data: scouting data to save
        :type data: dict

        :rtype bool
        """
        result = self.scouting.update_one({
            'event_key': data['event_key'],
            'team_key': data['team_key'],
        }, {'$set': {
            'pit': data
        }}, upsert=True)
        return result.upserted_id or result.matched_count or result.modified_count

    def scouting_stats(self, event_key, matches=0):
        """Return aggregated scouting stats per JSON config.

        :param event_key: event key to query with
        :param matches: number of matches to include (Default value = 0)
        :type event_key: string
        :type matches: int

        :rtype dict
        """
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
            year_scatter = {}
            if isinstance(year_stats, dict):
                if 'individual' in year_stats:
                    year_individual = year_stats['individual']
                if 'scatter' in year_stats:
                    year_scatter = year_stats['scatter']

        aggregation = [
            # Get matches from TBA data (so they're in order)
            {'$match': {'key': event_key}},
            # Fill in missing match list to allow for $unwind:$matches
            {'$addFields': {'matches': {'$ifNull': ['$matches',
                                                    [{
                                                        'key': {'$concat': ['$key', '_qm' + str(match_number)]},
                                                        'event_key': '$key'
                                                    } for match_number in range(250)] +
                                                    [{
                                                        'key': {'$concat': ['$key', '_' + comp_level + str(
                                                            match_number) + 'm' + str(set_number)]},
                                                        'event_key': '$key'
                                                    } for comp_level in ['ef', 'qf', 'sf', 'f'] for match_number in
                                                        range(8) for set_number in range(3)]
                                                    ]}}},
            # Add practice matches
            {'$addFields': {'matches': {'$concatArrays': ['$matches', [{
                'key': {'$concat': ['$key', '_p' + str(match_number)]},
                'event_key': '$key'
            } for match_number in range(50)]]}}},
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
                'match_key': {'$concat': ['$event_key', '_p1']},
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
                '_team_number': {'$ifNull': ['$_team_number', '$_id']}
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
                'dataset': {t['_team_number']: {k: t[year_scatter['dataset'][k]] for k in year_scatter['dataset']} for t
                            in individual}
            } if year_scatter else year_scatter
        }

    def teams(self):
        """List of all teams

        :rtype list
        """
        return list(self.tba_teams.find())

    def teams_paged(self, page, limit=500):
        """List of all teams, paged.

        :param page: page number
        :param limit: results limit (Default value = 500)
        :type page: int, string
        :type limit: int, string

        :rtype list
        """
        min_num = int(page) * limit
        max_num = (int(page) + 1) * limit - 1
        return list(self.tba_teams.find({'team_number': {'$gte': min_num, '$lte': max_num}}))

    def teams_list(self, team_keys):
        """List of teams, given a set of team keys.

        :param team_keys: list of team keys to query with
        :type team_keys: list

        :rtype list
        """
        return list(self.tba_teams.find({'key': {'$in': team_keys}}).sort('team_number'))

    def teams_stats(self):
        """Count, min, and max of all team numbers.

        :rtype dict
        """
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

    def teams_update(self):
        """TBA update the team listing."""
        teams = self.tba_api.teams_all(True)
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

    def team(self, team_key, year=None):
        """Team information.

        :param team_key: team key to query with
        :param year: year to query for (Default value = None)
        :type team_key: string
        :type year: int, None

        :rtype dict
        """
        team = list(self.tba_teams.find({'key': team_key}))
        if team:
            team = team[0]
            if year is not None:
                team['events'] = self.team_events(team_key, year)
            return team
        else:
            return {}

    def team_update(self, team_key, update_favicon=False):
        """TBA update an individual team.

        :param team_key: team to update
        :param update_favicon: should favicon be updated (Default value = False)
        :type team_key: string
        :type update_favicon: bool
        """
        team = self.tba_api.team(team_key, True)
        if team:
            team.update({k: v for k, v in {
                'awards': self.tba_api.team_history_awards(team_key),
                'districts': {str(d['year']): d for d in self.tba_api.team_districts(team_key)},
                'favicon': sharkscout.Util.favicon(
                    team['website'] if 'website' in team else '') if update_favicon else None,
                'media': self.tba_api.team_media(team_key)
            }.items() if v})
            team['modified_timestamp'] = datetime.utcnow()
            self.tba_teams.update_one({
                'key': team_key
            }, {
                '$set': team,
                '$setOnInsert': {'created_timestamp': datetime.utcnow()}
            }, upsert=True)

    def team_stats(self, team_key):
        """Years that a team competed.

        :param team_key: team key to query with
        :type team_key: string

        :rtype dict
        """
        return {
            'years': sorted(self.tba_events.find({'teams': team_key}).distinct('year'), reverse=True)
        }

    def team_events(self, team_key, year):
        """Events a team is attending in a given year.

        :param team_key: team key to query with
        :param year: year to query for
        :type team_key: string
        :type year: int, string

        :rtype list
        """
        # Query
        events = list(self.tba_events.find({'teams': team_key, 'year': int(year)}).sort('start_date'))

        for event_idx, event in enumerate(events):
            # Infer missing match information from scouting information
            if 'matches' not in event:
                event.update({'matches': self.scouting_matches(event['key'])})

            if 'matches' in event:
                # Filter matches
                event['matches'] = [m for m in event['matches'] if
                                    team_key in m['alliances']['red']['teams'] or
                                    team_key in m['alliances']['blue']['teams']]

                # Attach scouting data
                scouting = self.scouting_matches_teams(event['key'])
                for match_idx, match in enumerate(event['matches']):
                    if match['key'] in scouting:
                        match['scouting'] = scouting[match['key']]
                    event['matches'][match_idx] = match

            events[event_idx] = event

        return events

    def team_update_events(self, team_key, year):
        """TBA update all events a team is attending in a given year.

        :param team_key: team to update
        :param year: year to update
        :type team_key: string
        :type year: int, string
        """
        for event in self.tba_api.team_events(team_key, int(year), True):
            self.event_update(event['key'])
