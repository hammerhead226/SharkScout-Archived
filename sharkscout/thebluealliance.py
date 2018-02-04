import backoff
from datetime import date, datetime
import json
import os
import re
import requests
import sys


class TheBlueAlliance(object):
    tba_auth_key = None

    def __init__(self):
        if self.__class__.tba_auth_key is None:
            config = os.path.join(getattr(sys, '_MEIPASS', os.path.abspath('.')), 'config.json')
            with open(config, 'r') as f:
                self.__class__.tba_auth_key = json.loads(f.read())['tba_auth_key']
                if not self.__class__.tba_auth_key:
                    raise Exception('Invalid tba_auth_key in config.json')

    @backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=3)
    def _get(self, endpoint, modified_timestamp=None):
        if self.__class__.tba_auth_key is None:
            return {}

        headers = {
            'User-Agent': 'Mozilla/5.0',
            'X-TBA-Auth-Key': self.__class__.tba_auth_key
        }
        if modified_timestamp is not None:
            if isinstance(modified_timestamp, datetime):
                modified_timestamp = modified_timestamp.strftime('%a, %d %b %Y %H:%M:%S UTC')
            headers['If-Modified-Since'] = modified_timestamp

        response = requests.get('https://www.thebluealliance.com/api/v3/' + endpoint, headers=headers, timeout=5)

        # cherrypy-like logging
        print(
            '0.0.0.0 - -'
            + ' [' + datetime.today().strftime('%d/%b/%Y:%H:%M:%S') + ']'
            + ' "' + response.request.method + ' ' + response.url + '"'
            + ' ' + str(response.status_code)
            + ' ' + str(len(response.content))
            + ' ""'
            + ' "' + response.request.headers['User-Agent'] + '"'
        )

        # Hide errors
        if 400 <= response.status_code and response.status_code <= 499:
            return {}

        # Not modified
        if modified_timestamp is not None and response.status_code == 304:
            return {}

        content = response.json()
        content = self._tba3_to_tba2(content)
        return content

    @staticmethod
    def _tba3_to_tba2(models):
        if models is None:
            return models

        models_list = models if isinstance(models, list) else [models]

        for idx, model in enumerate(models_list):
            if not sum([0 if k in model else 1 for k in ['name', 'award_type', 'event_key', 'recipient_list']]):
                # Award
                pass
            elif not sum([0 if k in model else 1 for k in ['key', 'team_number', 'name', 'rookie_year']]):
                # Team
                model['country_name'] = model['country']
                model['locality'] = model['city']
                model['region'] = model['state_prov']
            elif not sum([0 if k in model else 1 for k in ['key', 'name', 'event_code', 'event_type', 'start_date', 'end_date', 'year', 'event_type_string']]):
                # Event
                model['event_district'] = model['district']['abbreviation'] if model['district'] else None
                model['event_district_string'] = model['district']['display_name'] if model['district'] else None
                model['venue_address'] = model['address']
                model['webcast'] = model['webcasts']
            elif not sum([0 if k in model else 1 for k in ['key', 'comp_level', 'set_number', 'match_number', 'event_key']]):
                # Match
                pass

            if not sum([0 if k in model else 1 for k in ['city', 'state_prov', 'postal_code', 'country']]):
                model['location'] = (model['city'] or '') + ', ' + (model['state_prov'] or '') + ' ' + (model['postal_code'] or '') + ', ' + (model['country'] or '')
                model['location'] = model['location'].replace('  ', ' ')
                model['location'] = model['location'].replace(' ,', ',')
                model['location'] = model['location'].lstrip(', ').rstrip(', ')
                model['location'] = model['location'] if model['location'] else None

            models_list[idx] = model

        return models_list if isinstance(models, list) else models_list[0]

    @staticmethod
    def _team_map(teams):
        for idx, team in enumerate(teams):
            if 'country_name' in team and team['country_name'] == 'USA':
                states = {
                    'Alaska': 'AK', 'Alabama': 'AL', 'Arkansas': 'AR', 'American Samoa': 'AS', 'Arizona': 'AZ',
                    'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'District of Columbia': 'DC',
                    'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA', 'Guam': 'GU', 'Hawaii': 'HI', 'Iowa': 'IA',
                    'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Kansas': 'KS', 'Kentucky': 'KY',
                    'Louisiana': 'LA', 'Massachusetts': 'MA', 'Maryland': 'MD', 'Maine': 'ME', 'Michigan': 'MI',
                    'Minnesota': 'MN', 'Missouri': 'MO', 'Northern Mariana Islands': 'MP', 'Mississippi': 'MS',
                    'Montana': 'MT', 'National': 'NA', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Nebraska': 'NE',
                    'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'Nevada': 'NV', 'New York': 'NY',
                    'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA', 'Puerto Rico': 'PR',
                    'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD', 'Tennessee': 'TN',
                    'Texas': 'TX', 'Utah': 'UT', 'Virginia': 'VA', 'Virgin Islands': 'VI', 'Vermont': 'VT',
                    'Washington': 'WA', 'Wisconsin': 'WI', 'West Virginia': 'WV', 'WY': 'Wyoming'
                }
                if 'region' in team and team['region'] in states:
                    team['region'] = states[team['region']]
            # TODO: CANADA MAPPING
            teams[idx] = team
        return teams

    def teams(self, page_num=0, modified_timestamp=None):
        teams = self._get('teams/' + str(page_num), modified_timestamp)
        teams = [t for t in teams if t['nickname'] and t['name'] != 'Team ' + str(t['team_number'])]
        teams = self._team_map(teams)
        return teams

    def teams_all(self, modified_timestamp=None):
        teams = []
        page_num = 0
        while True:
            page = self.teams(page_num, modified_timestamp)
            if not page:
                break
            teams.extend(page)
            page_num += 1
        return teams

    def team(self, team_key, modified_timestamp=None):
        return self._get('team/' + team_key, modified_timestamp)

    def team_awards(self, team_key, year=None, modified_timestamp=None):
        return self._get('team/' + team_key + '/awards' + ('/' + str(year) if year else ''), modified_timestamp)

    def team_districts(self, team_key, modified_timestamp=None):
        return self._get('team/' + team_key + '/districts', modified_timestamp)

    def team_events(self, team_key, year=None, modified_timestamp=None):
        return self._get('team/' + team_key + '/events' + ('/' + str(year) if year else ''), modified_timestamp)

    def team_event_awards(self, team_key, event_key, modified_timestamp=None):
        return self._get('team/' + team_key + '/event/' + event_key + '/awards', modified_timestamp)

    def team_event_matches(self, team_key, event_key, modified_timestamp=None):
        return self._get('team/' + team_key + '/event/' + event_key + '/matches', modified_timestamp)

    def team_years_participated(self, team_key, modified_timestamp=None):
        return self._get('team/' + team_key + '/years_participated', modified_timestamp)

    def team_media(self, team_key, year=None, modified_timestamp=None):
        return self._get('team/' + team_key + '/media' + ('/' + str(year) if year else ''), modified_timestamp)

    def team_robots(self, team_key, modified_timestamp=None):
        return self._get('team/' + team_key + '/robots', modified_timestamp)

    # Deprecated
    def team_history_events(self, team_key, modified_timestamp=None):
        return self.team_events(team_key, modified_timestamp)

    # Deprecated
    def team_history_awards(self, team_key, modified_timestamp=None):
        return self.team_awards(team_key, modified_timestamp)

    # Deprecated
    def team_history_robots(self, team_key, modified_timestamp=None):
        return self.team_robots(team_key, modified_timestamp)

    # Deprecated
    def team_history_districts(self, team_key, modified_timestamp=None):
        return self.team_districts(team_key, modified_timestamp)

    def events(self, year=None, modified_timestamp=None):
        if year is None:
            year = date.today().year
        return self._get('events/' + str(year), modified_timestamp)

    def event(self, event_key, modified_timestamp=None):
        return self._get('event/' + event_key, modified_timestamp)

    def event_teams(self, event_key, modified_timestamp=None):
        teams = self._get('event/' + event_key + '/teams', modified_timestamp)
        teams = self._team_map(teams)
        return teams

    def event_matches(self, event_key, modified_timestamp=None):
        matches = self._get('event/' + event_key + '/matches', modified_timestamp)
        return sorted(matches, key=lambda m: (m['time'] or 0))

    def event_oprs(self, event_key, modified_timestamp=None):
        return self._get('event/' + event_key + '/oprs', modified_timestamp)

    # Deprecated
    def event_stats(self, event_key, modified_timestamp=None):
        return self.event_oprs(event_key, modified_timestamp)

    def event_rankings_raw(self, event_key, modified_timestamp=None):
        return self._get('event/' + event_key + '/rankings', modified_timestamp)

    def event_rankings_v2(self, event_key, modified_timestamp=None):
        rankings = self.event_rankings_raw(event_key, modified_timestamp)
        if rankings is None:
            return rankings
        for idx, ranking in enumerate(rankings['rankings']):
            rankings['rankings'][idx] = [
                ranking['rank'],
                ranking['team_key']
            ] + ranking['sort_orders'] + [
                ranking['record']['wins'] + '-' + ranking['record']['losses'] + '-' + ranking['record']['ties'],
                ranking['matches_played']
            ]
        rankings['rankings'].insert(0, ['Rank', 'Team'] + [i['name'] for i in rankings['sort_order_info']] + ['Record (W-L-T)', 'Played'])
        return rankings['rankings']

    def event_rankings(self, event_key, modified_timestamp=None):
        rankings = self.event_rankings_v2(event_key, modified_timestamp)
        if rankings:
            # Change value names to snake case
            header = rankings.pop(0)
            for idx, w_l_t in enumerate(header):
                header[idx] = re.sub(r'[^a-z]+', '_', w_l_t.lower()).rstrip('_')

            # Change each row to a dictionary
            for idx, ranking in enumerate(rankings):
                ranking = dict(zip(header, ranking))
                for key in list(ranking.keys()):
                    # Cast values
                    if str(ranking[key]).lstrip('-').replace('.', '', 1).isdigit():  # numeric
                        if str(ranking[key]).lstrip('-').rstrip('0').rstrip('.').isdigit():  # int
                            ranking[key] = int(re.sub(r'\.0+$', '', str(ranking[key])))
                        else:  # float
                            ranking[key] = float(ranking[key])

                    # Normalize wins/losses/ties
                    if 'w_l_t' in key:
                        w_l_t = re.split(r'[^0-9]+', ranking[key])
                        if len(w_l_t) == 3:
                            ranking['wins'] = int(w_l_t[0])
                            ranking['losses'] = int(w_l_t[1])
                            ranking['ties'] = int(w_l_t[2])
                            ranking.pop(key)

                rankings[idx] = ranking

            return dict(zip([str(r['team']) for r in rankings[1:]], rankings[1:]))

        return {}

    def event_awards(self, event_key, modified_timestamp=None):
        return self._get('event/' + event_key + '/awards', modified_timestamp)

    def event_district_points(self, event_key, modified_timestamp=None):
        return self._get('event/' + event_key + '/district_points', modified_timestamp)

    def event_alliances(self, event_key, modified_timestamp=None):
        return self._get('event/' + event_key + '/alliances', modified_timestamp)

    def match(self, match_key, modified_timestamp=None):
        return self._get('match/' + match_key, modified_timestamp)

    def districts(self, year, modified_timestamp=None):
        return self._get('districts/' + str(year), modified_timestamp)

    def district_events(self, district_key, year, modified_timestamp=None):
        return self._get('district/' + district_key + '/' + year + '/events', modified_timestamp)

    def district_rankings(self, district_key, modified_timestamp=None):
        return self._get('district/' + district_key + '/rankings', modified_timestamp)

    def district_teams(self, district_key, modified_timestamp=None):
        return self._get('district/' + district_key + '/teams', modified_timestamp)
