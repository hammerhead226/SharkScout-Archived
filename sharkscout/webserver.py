import cherrypy
import csv
from datetime import datetime, date
import genshi.core
import genshi.template
import json
import os
import random
import re
import string
import sys
import tempfile
import threading
import ws4py.server.cherrypyserver
import ws4py.websocket

import sharkscout


class WebServer(threading.Thread):
    def __init__(self, port):
        sessions_path = os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'sessions'))
        if not os.path.exists(sessions_path):
            os.mkdir(sessions_path)

        self.cherry_config = {
            'global': {
                'server.socket_host': '0.0.0.0',
                'server.socket_port': port,
                'engine.autoreload.on': False
            },
            '/': {
                'tools.sessions.on': True,
                'tools.sessions.locking': 'early',
                'tools.sessions.storage_class': cherrypy.lib.sessions.FileSession,
                'tools.sessions.storage_path': sessions_path,
                'tools.gzip.on': True,
                'tools.gzip.mime_types': ['application/*', 'image/*', 'text/*']
            },
            '/static': {
                'tools.staticdir.on': True,
                'tools.staticdir.dir': os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'www/static')),
                'tools.expires.on': True,
                'tools.expires.secs': 12 * 60 * 60,  # 12 hours
                'tools.sessions.on': False  # otherwise locking throws frequent 500 errors
            },
            '/ws': {
                'tools.websocket.on': True,
                'tools.websocket.handler_cls': WebSocketServer,
                'tools.gzip.on': False,    # otherwise websockets will always fail
                'tools.expires.on': False  # otherwise websockets will usually not connect
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

    @property
    def running(self):
        try:
            return cherrypy.server.running
        except:
            return False

    @property
    def port(self):
        try:
            return cherrypy.server.bound_addr[1]
        except:
            return 0


class CherryServer(object):
    def __init__(self):
        self.www = os.path.normpath(os.path.join(os.path.dirname(sys.argv[0]), 'www'))
        self.template_loader = genshi.template.TemplateLoader(self.www, auto_reload=True)

    def display(self, template, page={}):
        cherrypy.session['refresh'] = cherrypy.request.path_info

        page['__TEMPLATE__'] = template
        page['__CONTENT__'] = self.render(template, page)
        return self.render('www', page, False)

    def can_render(self, template):
        return os.path.exists(os.path.join(self.www, template + '.html'))

    def render(self, template, page={}, strip_html=True):
        for key in ['team_number', 'user_name']:
            if key not in cherrypy.session:
                cherrypy.session[key] = ''

        if 'year' not in page or ('year_defaulted' in page and page['year_defaulted']):
            page['year'] = date.today().year
            page['year_defaulted'] = True
        else:
            page['year_defaulted'] = False

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

        # Pack <link> and <script> to fewer files
        def packer(stream):
            # Find all files to be packed, included packed file
            has_html = False
            static_files = {}
            ns = None
            for kind, data, pos in stream:
                strip = False
                if kind is genshi.core.START_NS:
                    ns = data[1]
                if kind is genshi.core.START:
                    tag = data
                    if type(tag) is tuple:
                        tag = tag[0]
                    tag = str(tag).replace('{' + ns + '}', '')
                    if tag == 'html':
                        has_html = True
                    if tag in ['link', 'script']:
                        data_1 = list(data[1])
                        for idx, attr in enumerate(data_1):
                            if attr[0] in ['href', 'src']:
                                # If this is a local file
                                absolute = os.path.normpath(os.path.join(self.www, attr[1].lstrip('/')))
                                if os.path.exists(absolute):
                                    extension = os.path.splitext(attr[1])[1]
                                    if extension.lstrip('.') in ['css', 'js']:
                                        if extension not in static_files:
                                            static_files[extension] = {}
                                        directory = os.path.dirname(absolute)
                                        if directory not in static_files[extension]:
                                            static_files[extension][directory] = []
                                        static_files[extension][directory].append(absolute)
                                        if len(static_files[extension][directory]) > 1:
                                            strip = True
                                        data_1[idx] = (attr[0], os.path.join(os.path.dirname(attr[1]), 'packed' + extension).replace('\\', '/'))
                        data = (data[0], genshi.core.Attrs(data_1))
                if not strip:
                    yield kind, data, pos

            # If we're rendering the parent template with <html>
            if has_html:
                # Delete old packed files on first run
                if not hasattr(self.__class__, 'packed'):
                    for root, dirs, files in os.walk(self.www):
                        for file in files:
                            if os.path.splitext(file)[0] == 'packed':
                                os.remove(os.path.join(root, file))
                # Pack files that don't exist
                for extension in static_files:
                    for directory in static_files[extension]:
                        packed = os.path.join(directory, 'packed' + extension)
                        if not os.path.exists(packed):
                            contents = b''
                            for file in static_files[extension][directory]:
                                with open(file, 'rb') as f:
                                    contents += f.read().strip() + b'\n'
                            with open(packed, 'wb') as f:
                                f.write(contents)
                self.__class__.packed = True

        # Add a random hash to <link href=""> and <script src="">
        def static_hash(stream):
            if not hasattr(self.__class__, 'static_hash'):
                self.__class__.static_hash = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
            ns = None
            for kind, data, pos in stream:
                if kind is genshi.core.START_NS:
                    ns = data[1]
                if kind is genshi.core.START:
                    tag = data
                    if type(tag) is tuple:
                        tag = tag[0]
                    tag = str(tag).replace('{' + ns + '}', '')
                    if tag in ['link', 'script']:
                        data_1 = list(data[1])
                        for idx, attr in enumerate(data_1):
                            if attr[0] in ['href', 'src']:
                                data_1[idx] = (attr[0], attr[1] + '?' + self.__class__.static_hash)
                        data = (data[0], genshi.core.Attrs(data_1))
                yield kind, data, pos

        # Generate the basic stream
        stream = self.template_loader.load(template + '.html').generate(page=page, session=cherrypy.session)
        # Filter the stream
        if strip_html:
            stream = stream.filter(strip)
        stream = stream.filter(packer)
        stream = stream.filter(static_hash)
        # Render the stream
        return genshi.core.Markup(stream.render('html'))

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
        return self.display('index')

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['POST'])
    def settings(self, **kwargs):
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
            'events_attending': [e for e in events if 'teams' in e and 'team_number' in cherrypy.session and 'frc' + cherrypy.session['team_number'] in e['teams']],
            'events_active': [e for e in events if e['start_date'] and datetime.strptime(e['start_date'],'%Y-%m-%d').date() <= date.today() and e['end_date'] and date.today() <= datetime.strptime(e['end_date'],'%Y-%m-%d').date()],
            'events_district': [],
            'events_upcoming': [e for e in events if e['start_date'] and datetime.strptime(e['start_date'],'%Y-%m-%d').date() > date.today()]
        }
        if 'team_number' in cherrypy.session:
            team = sharkscout.Mongo().team('frc' + str(cherrypy.session['team_number']))
            if 'districts' in team and str(year) in team['districts']:
                district = team['districts'][str(year)]
                page.update({
                    'district': district,
                    'events_district': [e for e in events if 'district' in e and e['district'] and e['district']['abbreviation'] == district['abbreviation']]
                })
        return self.display('events', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def event(self, event_key, stats_matches=0):
        event = sharkscout.Mongo().event(event_key)
        page = {
            'event': event,
            'stats_matches': int(stats_matches),
            'stats': sharkscout.Mongo().scouting_stats(event_key, stats_matches),
            'years': sharkscout.Mongo().event_years(event['event_code']),
            'can_scout': {
                'match': self.can_render('scouting/' + str(event['year']) + '/match'),
                'pit': self.can_render('scouting/' + str(event['year']) + '/pit')
            },
            'modified_timestamp': event['modified_timestamp']
        }
        return self.display('event', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def stats(self, event_key, match_key):
        event = sharkscout.Mongo().event(event_key)

        matches = [m for m in event['matches'] if m['key'] == match_key] if match_key else []
        match = matches[0] if matches else {}

        stats = sharkscout.Mongo().scouting_stats(event_key)

        alliance_stats = {}
        for alliance in match['alliances']:
            alliance_stats[alliance] = [s for s in stats if s['_id'] in match['alliances'][alliance]['teams']]

        page = {
            'event': event,
            'match': match,
            'alliance_stats': alliance_stats
        }
        return self.display('stats', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def teams(self, team_page=0):
        page = {
            'team_page': int(team_page),
            'stats': sharkscout.Mongo().teams_stats(),
            'teams': sharkscout.Mongo().teams_paged(team_page)
        }
        return self.display('teams', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def team(self, team_key, year=None):
        if year is None:
            year = date.today().year
        team = sharkscout.Mongo().team(team_key, year)
        page = {
            'team': team,
            'year': year,
            'stats': sharkscout.Mongo().team_stats(team_key),
            'can_scout': {
                'match': self.can_render('scouting/' + str(year) + '/match'),
                'pit': self.can_render('scouting/' + str(year) + '/pit')
            },
            'modified_timestamp': team['modified_timestamp']
        }
        return self.display('team', page)

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

        matches = [m for m in event['matches'] if m['key'] == match_key] if match_key else []
        match = matches[0] if matches else {}

        teams = {
            'blue': [''.join([c for c in t if c.isdigit()]) for t in match['alliances']['blue']['teams']],
            'red': [''.join([c for c in t if c.isdigit()]) for t in match['alliances']['red']['teams']]
        } if match else {}

        team = sharkscout.Mongo().team(team_key, event['year']) if team_key else {}
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
        page['__FORM__'] = self.render('scouting/' + str(event['year']) + '/match', page)
        return self.display('scout_match', page)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def pit(self, event_key, team_key=None):
        event = sharkscout.Mongo().event(event_key)
        team = sharkscout.Mongo().team(team_key, event['year']) if team_key else {}

        saved = {}
        if event_key and team_key:
            saved = sharkscout.Mongo().scouting_pit(event_key, team_key)

        page = {
            'event': event,
            'teams': event['teams'] if 'teams' in event else [],
            'team': team,
            'saved': saved
        }
        page['__FORM__'] = self.render('scouting/' + str(event['year']) + '/pit', page)
        return self.display('scout_pit', page)


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
            items = [items[k] for k in sorted(items)]

        # Find all possible keys, sort them
        keys = []
        for item in items:
            for key in item:
                if not key.startswith('_') and key not in keys:
                    keys.append(key)
        keys = sorted(keys)

        # Open up the temp file for CSV writing
        filename = tempfile.gettempdir() + '/' + prefix + datetime.now().strftime('%Y%m%d-%H%M%S') + '.csv'
        with open(filename, 'w', newline='') as temp:
            writer = csv.DictWriter(temp, fieldnames=keys)
            writer.writerow({k: re.sub(r'^[0-9]+_+', '', k) for k in keys})
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

    @cherrypy.expose
    @cherrypy.tools.allow(methods=['GET'])
    def stats(self, event_key, stats_matches):
        stats = sharkscout.Mongo().scouting_stats(event_key, stats_matches)
        return self._csv(event_key + '_scouting_stats_', stats)


class WebSocketServer(ws4py.websocket.WebSocket):
    sockets = []

    def opened(self):
        self.__class__.sockets.append(self)
        print(self, 'Opened', '(Total: ' + str(len(self.__class__.sockets)) + ')')
        # Note: can't send any messages here

    def received_message(self, message):
        message = message.data.decode()
        try:
            message = json.loads(message)

            if 'ping' in message:
                self.send({'pong':'pong'})

            if 'time_team' in message:
                self.send({'time_team':sharkscout.Mongo().team(message['time_team'])})

            # Match scouting upserts
            if 'scouting_match' in message:
                for data in message['scouting_match']:
                    if sharkscout.Mongo().scouting_match_update(data):
                        self.send({'dequeue': {'scouting_match': data}})
                        self.broadcast({
                            'show': '.match-listing .' + data['match_key'] + ' .' + data['team_key'] + ' .fa-check',
                            'success': data['scouter'] + ' match scouted ' + data['match_key'] + ' ' + data['team_key']
                        })

            # Pit scouting upserts
            if 'scouting_pit' in message:
                for data in message['scouting_pit']:
                    if sharkscout.Mongo().scouting_pit_update(data):
                        self.send({'dequeue': {'scouting_pit': data}})
                        self.broadcast({
                            'show': '.team-listing .' + data['team_key'] + ' .fa-check',
                            'success': data['scouter'] + ' pit scouted ' + data['event_key'] + ' ' + data['team_key']
                        })

        except json.JSONDecodeError as e:
            print(e)

    def closed(self, code, reason=None):
        if self in self.__class__.sockets:
            self.__class__.sockets.remove(self)
        print(self, 'Closed', code, reason, '(Open: ' + str(len(self.__class__.sockets)) + ')')

    def send(self, payload, binary=False):
        def basic(data):
            if isinstance(data, dict):
                for key in data:
                    data[key] = basic(data[key])
            elif isinstance(data, list):
                for idx, val in enumerate(data):
                    data[idx] = basic(val)
            elif not isinstance(data, (int, float, bool)) and data is not None:
                data = str(data)
            return data
        payload = basic(payload)
        if type(payload) is dict:
            payload = json.dumps(payload)
        super(self.__class__, self).send(payload, binary)

    def broadcast(self, payload):
        for socket in self.__class__.sockets:
            socket.send(payload)
