import backoff
from datetime import date
import re
import requests


class TheBlueAlliance(object):
    app_id = None

    def __init__(self, app_id=None):
        # Allow app ID to be "cached" in a static variable
        self.app_id = self.__class__.app_id
        if app_id is not None:
            self.app_id = app_id
            self.__class__.app_id = self.app_id

    @backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=3)
    def _get(self, endpoint):
        if self.app_id is None:
            return {}

        response = requests.get('https://www.thebluealliance.com/api/v2/' + endpoint, headers={
            'User-Agent': 'Mozilla/5.0',  # throws a 403 without this
            'X-TBA-App-Id': self.app_id
        }, timeout=5)
        if 400 <= response.status_code and response.status_code <= 499:
            return {}
        content = response.json()
        return content

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

    def teams(self, page_num=0):
        teams = [t for t in self._get('teams/' + str(page_num)) if t['nickname']]
        teams = self._team_map(teams)
        return teams

    def teams_all(self):
        teams = []
        page_num = 0
        while True:
            page = self.teams(page_num)
            if not page:
                break
            teams.extend(page)
            page_num += 1
        return teams

    def team(self, team_key):
        return self._get('team/' + team_key)

    def team_events(self, team_key, year=None):
        return self._get('team/' + team_key + ('/' + str(year) if year else '') + '/events')

    def team_awards(self, team_key, event_key):
        return self._get('team/' + team_key + '/event/' + event_key + '/awards')

    def team_event_matches(self, team_key, event_key):
        return self._get('team/' + team_key + '/event/' + event_key + '/matches')

    def team_years_participated(self, team_key):
        return self._get('team/' + team_key + '/years_participated')

    def team_media(self, team_key, year=None):
        return self._get('team/' + team_key + ('/' + str(year) if year else '') + '/media')

    def team_history_events(self, team_key):
        return self._get('team/' + team_key + '/history/events')

    def team_history_awards(self, team_key):
        return self._get('team/' + team_key + '/history/awards')

    def team_history_robots(self, team_key):
        return self._get('team/' + team_key + '/history/robots')

    def team_history_districts(self, team_key):
        return self._get('team/' + team_key + '/history/districts')

    def events(self, year=None):
        if year is None:
            year = date.today().year
        return self._get('events/' + str(year))

    def event(self, event_key):
        return self._get('event/' + event_key)

    def event_teams(self, event_key):
        teams = self._get('event/' + event_key + '/teams')
        teams = self._team_map(teams)
        return teams

    def event_matches(self, event_key):
        matches = self._get('event/' + event_key + '/matches')
        return sorted(matches, key=lambda m: (m['time'] or 0))

    def event_stats(self, event_key):
        return self._get('event/' + event_key + '/stats')

    def event_rankings_raw(self, event_key):
        return self._get('event/' + event_key + '/rankings')

    def event_rankings(self, event_key):
        rankings = self.event_rankings_raw(event_key)
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

    def event_awards(self, event_key):
        return self._get('event/' + event_key + '/awards')

    def event_district_points(self, event_key):
        return self._get('event/' + event_key + '/district_points')

    def match(self, match_key):
        return self._get('match/' + match_key)

    def districts(self, year):
        return self._get('districts/' + str(year))

    def district_events(self, district_short, year):
        return self._get('district/' + district_short + '/' + year + '/events')

    def district_rankings(self, district_short, year):
        return self._get('district/' + district_short + '/' + year + '/rankings')

    def district_teams(self, district_short, year):
        return self._get('district/' + district_short + '/' + year + '/teams')
