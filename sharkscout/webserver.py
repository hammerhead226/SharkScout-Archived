import cherrypy
import csv
from datetime import date
import genshi.core
import genshi.template
import json
import os
import random
import string
import sys
import tempfile
import threading
import time
import ws4py.server.cherrypyserver
import ws4py.websocket

import sharkscout


class WebServer(threading.Thread):
    def __init__(self):
        sessions_path = os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'sessions'))
        if not os.path.exists(sessions_path):
            os.mkdir(sessions_path)

        self.cherry_config = {
            'global': {
                'server.socket_host': '0.0.0.0',
                'server.socket_port': 2260,
                'engine.autoreload.on': False
            },
            '/': {
                'tools.sessions.on': True,
                'tools.sessions.locking': 'early',
                'tools.sessions.storage_class': cherrypy.lib.sessions.FileSession,
                'tools.sessions.storage_path': sessions_path
            },
            '/static': {
                'tools.staticdir.on': True,
                'tools.staticdir.dir': os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'www/static'))
            },
            '/ws': {
                'tools.websocket.on': True,
                'tools.websocket.handler_cls': WebSocketServer
            }
        }
        self.cherry = None
        threading.Thread.__init__(self)

    def run(self):
        ws4py.server.cherrypyserver.WebSocketPlugin(cherrypy.engine).subscribe()
        cherrypy.tools.websocket = ws4py.server.cherrypyserver.WebSocketTool()
        self.cherry = cherrypy.quickstart(Index(), '', self.cherry_config)

    def stop(self):
        cherrypy.engine.exit()


class CherryServer(object):
    def __init__(self):
        self.template_loader = genshi.template.TemplateLoader(
            os.path.join(os.path.dirname(sys.argv[0]), 'www'),
            auto_reload=True
        )

    def render(self, template, page={}):
        cherrypy.session['refresh'] = cherrypy.request.path_info

        session_enforce = ['team_number', 'user_name', 'cache']
        for key in session_enforce:
            if key not in cherrypy.session:
                cherrypy.session[key] = ''

        page['__CACHE__'] = cherrypy.session['cache']
        page['__TEMPLATE__'] = template
        try:
            def strip(stream):
                ns = None
                for kind, data, pos in stream:
                    # Strip <!DOCTYPE>
                    if kind is genshi.core.DOCTYPE:
                        continue
                    if kind is genshi.core.START_NS:
                        ns = data[1]
                    # Strip <html>
                    if ns is not None:
                        if kind is genshi.core.START or kind is genshi.core.END:
                            tag = data
                            if type(tag) is tuple:
                                tag = tag[0]
                            tag = str(tag).replace('{' + ns + '}', '')
                            if tag == 'html':
                                continue
                    yield kind, data, pos
            page['__CONTENT__'] = genshi.core.Markup(self.template_loader.load(template + '.html').generate(page=page, session=cherrypy.session).filter(strip).render('html'))
        except genshi.template.loader.TemplateNotFound:
            raise cherrypy.HTTPRedirect('/')
        return self.template_loader.load('www.html').generate(page=page, session=cherrypy.session).render('html', doctype='html')

    def refresh(self):
        if 'refresh' in cherrypy.session:
            raise cherrypy.HTTPRedirect(cherrypy.session['refresh'])
        raise cherrypy.HTTPRedirect('/')


class Index(CherryServer):
    def __init__(self):
        super(self.__class__, self).__init__()
        self.scout = Scout()  # /scout/*
        self.update = Update()  # /update/*
        self.download = Download()  # /download/*

    # @cherrypy.expose
    # @cherrypy.tools.allow(methods=['GET'])
    def manifest(self):
        manifest = 'CACHE MANIFEST\r\n'
        # Build CACHE:
        manifest += 'CACHE:\r\n'
        mtime_max = 0
        static = []
        for search_path in self.template_loader.search_path:
            # Find the latest modified time of everything in the template loader paths
            for root, dirs, files in os.walk(search_path):
                for file in files:
                    mtime_max = max(mtime_max, os.path.getmtime(os.path.join(root, file)))
            # Find all static files in the template loader paths
            for root, dirs, files in os.walk(os.path.join(search_path, 'static')):
                for file in files:
                    relative = '/' + os.path.relpath(os.path.join(root, file), search_path).replace('\\', '/')
                    if relative not in static:
                        static.append(relative)
        manifest += '# mtime ' + str(mtime_max) + '\r\n'  # force manifest refreshing
        manifest += '\r\n'.join(static) + '\r\n'
        # Build NETWORK:
        manifest += 'NETWORK:\r\n*'
        cherrypy.response.headers['Content-Type'] = 'text/cache-manifest'
        return manifest

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def index(self):
        return self.render('index')

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['POST'])
    def settings(self, **kwargs):
        print(kwargs)
        for key in kwargs:
            cherrypy.session[key] = kwargs[key]
        return self.refresh()

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def events(self, year=None):
        if year is None:
            year = date.today().year
        events = sharkscout.Mongo().events(year)
        page = {
            'year': year,
            'stats': sharkscout.Mongo().events_stats(year),
            'events': events,
            'attending': [e for e in events if 'teams' in e and 'team_number' in cherrypy.session and 'frc' + cherrypy.session['team_number'] in e['teams']]
        }
        return self.render('events', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def event(self, event_key):
        event = sharkscout.Mongo().event(event_key)
        if not event:
            raise cherrypy.HTTPRedirect('/events')
        page = {
            'event': event,
            'years': sharkscout.Mongo().event_years(event['event_code'])
        }
        return self.render('event', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def teams(self, team_page=0):
        page = {
            'team_page': int(team_page),
            'stats': sharkscout.Mongo().teams_stats(),
            'teams': sharkscout.Mongo().teams_paged(team_page)
        }
        return self.render('teams', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def team(self, team_key, year=None):
        if year is None:
            year = date.today().year
        team = sharkscout.Mongo().team(team_key, year)
        if not team:
            raise cherrypy.HTTPRedirect('/teams')
        page = {
            'year': year,
            'stats': sharkscout.Mongo().team_stats(team_key),
            'team': team
        }
        return self.render('team', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def ws(self):
        pass


class Scout(CherryServer):
    def __init__(self):
        super(self.__class__, self).__init__()

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def match(self, event_key, match_key=None, team_key=None):
        event = sharkscout.Mongo().event(event_key)
        if event_key and not event:
            raise cherrypy.HTTPRedirect('/teams')

        matches = [m for m in event['matches'] if m['key'] == match_key] if match_key else []
        if match_key and not matches:
            raise cherrypy.HTTPRedirect('/scout/match/' + event_key)
        match = matches[0] if matches else {}

        teams = {
            'blue': [''.join([c for c in t if c.isdigit()]) for t in match['alliances']['blue']['teams']],
            'red': [''.join([c for c in t if c.isdigit()]) for t in match['alliances']['red']['teams']]
        } if match else {}

        team = sharkscout.Mongo().team(team_key, event['year']) if team_key else {}
        if team_key and not team:
            raise cherrypy.HTTPRedirect('/scout/match/' + event_key + '/' + match_key)
        if team:
            team['color'] = [c for c in teams if str(team['team_number']) in teams[c]]
            team['color'] = team['color'][0] if team['color'] else ''

        saved = {}
        if event_key and match_key and team_key:
            saved = sharkscout.Mongo().scouting_match(event_key, match_key, team_key)

        page = {
            'event': event,
            'match': match,
            'teams': teams,
            'team': team,
            'saved': saved
        }
        return self.render('scout_match', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def pit(self, event_key, team_key=None):
        event = sharkscout.Mongo().event(event_key)
        if event_key and not event:
            raise cherrypy.HTTPRedirect('/teams')

        team = sharkscout.Mongo().team(team_key, event['year']) if team_key else {}
        if team_key and not team:
            raise cherrypy.HTTPRedirect('/scout/pit/' + event_key)

        saved = {}
        if event_key and team_key:
            saved = sharkscout.Mongo().scouting_pit(event_key, team_key)

        page = {
            'event': event,
            'teams': event['teams'] if 'teams' in event else [],
            'team': team,
            'saved': saved
        }
        return self.render('scout_pit', page)


class Update(CherryServer):
    def __init__(self):
        super(self.__class__, self).__init__()

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def events(self, year):
        sharkscout.Mongo().events_update(year)
        raise cherrypy.HTTPRedirect('/events/' + year)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def event(self, event_key):
        sharkscout.Mongo().event_update(event_key)
        raise cherrypy.HTTPRedirect('/event/' + event_key)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def teams(self):
        sharkscout.Mongo().teams_update()
        raise cherrypy.HTTPRedirect('/teams')

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def team(self, team_key, path=None, *args):
        if path is None:
            sharkscout.Mongo().team_update(team_key)
        if path == 'events':
            sharkscout.Mongo().team_update_events(team_key, args[0])
            raise cherrypy.HTTPRedirect('/team/' + team_key + '/' + args[0])
        raise cherrypy.HTTPRedirect('/team/' + team_key)


class Download(CherryServer):
    def __init__(self):
        super(self.__class__, self).__init__()

    def _csv(self, prefix, items):
        # Enforce a list
        if type(items) is dict:
            items = [items[k] for k in items]
        # Find all possible keys, sort them
        keys = []
        for item in items:
            for key in item:
                if key not in keys:
                    keys.append(key)
        keys = sorted(keys)
        # Open up the temp file for CSV writing
        filename = tempfile.gettempdir() + '/' + prefix + ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8)) + '.csv'
        with open(filename, 'w', newline='') as temp:
            writer = csv.DictWriter(temp, fieldnames=keys)
            writer.writeheader()
            # Write each row
            for item in items:
                row = {}
                for key in keys:
                    row[key] = item[key] if key in item else ''
                writer.writerow(row)
        return cherrypy.lib.static.serve_file(filename, 'application/x-download', 'attachment')

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def matches(self, event_key):
        event = sharkscout.Mongo().event(event_key)
        matches = []
        if 'matches' in event:
            for match in event['matches']:
                row = {k: match[k] for k in ['comp_level', 'match_number', 'set_number', 'time']}
                for alliance in match['alliances']:
                    for idx, team in enumerate(match['alliances'][alliance]['teams']):
                        row[alliance + '_' + str(idx + 1)] = team
                matches.append(row)
        return self._csv(event_key + '_matches_', matches)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def scouting(self, type, event_key):
        if type == 'match':
            matches = sharkscout.Mongo().scouting_matches_raw(event_key)
            return self._csv(event_key + '_scouting_match_', matches)
        elif type == 'pit':
            teams = sharkscout.Mongo().scouting_pit_teams(event_key)
            return self._csv(event_key + '_scouting_pit_', teams)


class WebSocketServer(ws4py.websocket.WebSocket):
    def opened(self):
        print('Opened', self)

    def received_message(self, message):
        message = message.data.decode()
        try:
            message = json.loads(message)
            print(message)

            # Match scouting upserts
            if 'scouting_match' in message:
                for data in message['scouting_match']:
                    if sharkscout.Mongo().scouting_match_update(data):
                        self.send(json.dumps({'dequeue': {'scouting_match': data}}))

            # Pit scouting upserts
            if 'scouting_pit' in message:
                for data in message['scouting_pit']:
                    if sharkscout.Mongo().scouting_pit_update(data):
                        self.send(json.dumps({'dequeue': {'scouting_pit': data}}))

        except json.JSONDecodeError as e:
            print(e)

    def closed(self, code, reason=None):
        print('Closed', self)
