#!/usr/bin/env python3

import argparse
import atexit
import datetime
import os
import psutil
import re
import subprocess
import sys
import time
import urllib

import pynumparser
import requests
import scrapy.crawler
import scrapy.exceptions
import scrapy.spiders

import sharkscout


# SharkScout Scrapy spider
class Spider(scrapy.spiders.Spider):
    name = 'spider'
    custom_settings = {
        'TELNETCONSOLE_ENABLED': False,  # why would this be on by default?
        'DEPTH_PRIORITY': 1,             # breadth-first
        'DNS_TIMEOUT': 10,               # 10s timeout
        'DOWNLOAD_TIMEOUT': 10,          # 10s timeout
        'HTTPERROR_ALLOW_ALL': True      # let parse() deal with them
    }
    closed_reason = None
    allowed_domains = []
    url_regex = []

    def __init__(self, *args, **kwargs):
        self.__class__.closed_reason = None

        if 'start_url' in kwargs:
            self.__class__.start_urls = [kwargs.pop('start_url')]
        self.__class__.allowed_domains = [urllib.parse.urlparse(u).hostname for u in self.__class__.start_urls]

        if 'url_regex' in kwargs:
            self.__class__.url_regex = kwargs.pop('url_regex')

        super(self.__class__, self).__init__(*args, **kwargs)

    def parse(self, response):
        # Stop on any error
        if response.status >= 400:
            raise scrapy.exceptions.CloseSpider(int(response.status))

        urls = response.xpath("//*[not(contains(@class,'disabled'))]/@href").extract()

        # Prevent urllib.parse.urlparse() from being dumb...
        urls = [('http://' if 'www' in u else '') + u for u in urls]
        urls = [('http://' if u.endswith(('.com','.net','.org')) else '') + u for u in urls]

        # Actually obey allowed_domains...
        if self.__class__.allowed_domains:
            urls = [u for u in urls if urllib.parse.urlparse(u) not in self.__class__.allowed_domains + [None]]

        # URL massaging
        for idx, url in enumerate(urls):
            url = re.sub(r':///+', '://', url)
            url = response.urljoin(url)
            url = url.rstrip('/')
            urls[idx] = url

        # Yield logic
        for url in urls:
            if self.__class__.url_regex:
                for regex in self.__class__.url_regex:
                    if re.search(regex, url):
                        yield scrapy.Request(url)
                        continue
            else:
                yield scrapy.Request(url)

    # Remember why the spider stopped
    def closed(self, reason):
        self.__class__.closed_reason = reason


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('-l', '--level', metavar='[1-5]', help='testing level (default: 3)', type=pynumparser.Number(limits=(1, 5)), default=3)
    parser.add_argument('params', nargs='+')
    known, unknown = parser.parse_known_args()

    level = known.level
    params = known.params + unknown
    if params[0].endswith('.py'):
        params.insert(0, sys.executable)

    # Start SharkScout
    null = open(os.devnull, 'w')
    server = subprocess.Popen(params, stdout=subprocess.DEVNULL)

    # Stop SharkScout on quit
    @atexit.register
    def goodbye():
        # Terminate any processes with an open port
        procs = [psutil.Process(sharkscout.Util.pid_of_port(p)) for p in sharkscout.Util.pid_tree_ports(server.pid)]
        for proc in procs:
            proc.terminate()
        psutil.wait_procs(procs, timeout=5)
        null.close()

    # Wait for the web server to start
    print('Waiting for listening ports ...')
    ports = []
    while server.poll() is None:
        ports = sharkscout.Util.pid_tree_ports(server.pid)
        if len(ports) > 1:  # both mongod and web server
            break
        time.sleep(0.1)
    if not ports:
        sys.exit(1)
    print('Found ports:', ports)

    # Start twisted crawler process
    crawler = scrapy.crawler.CrawlerProcess({
        'USER_AGENT': 'Mozilla/5.0'
    })

    port_found = False
    for port in ports:
        # Basic HTTP root test
        url = 'http://localhost:' + str(port)
        try:
            requests.get(url).raise_for_status()
            port_found = True
        except requests.exceptions.RequestException as e:
            continue

        # Add scrawler
        year = str(datetime.date.today().year)
        paths = []
        if level >= 1:
            # This year's events, teams
            paths += [
                r'/events$',
                r'/event/' + year + '[^/]+$',
                r'/teams$',
                r'/teams/[0-9]+$',
                r'/team/frc[0-9]+$',
            ]
        if level >= 2:
            # Non-specific scouting forms
            paths += [
                r'/scout/pit/[0-9]+[^/]+$',
                r'/scout/match/[0-9]+[^/]+$',
            ]
        if level >= 3:
            # Events for all years, all events, all team years
            paths += [
                r'/events/[0-9]+$',
                r'/event/[0-9]+[^/]+$',
                r'/team/frc[0-9]+/[0-9]+$',
            ]
        if level >= 4:
            # Some specific scouting forms
            paths += [
                r'/scout/pit/[0-9]+[^/]+/frc[0-9]+$',
                r'/scout/match/[0-9]+[^/]+/[0-9]+[^/]+[a-z]1$',
                r'/scout/match/[0-9]+[^/]+/[0-9]+[^/]+[a-z]1/frc[0-9]+$'
            ]
        if level >= 5:
            # All paths
            paths += ['/.+']
        crawler.crawl(Spider(start_url=url, url_regex=[url + p for p in paths]))

    if not port_found:
        sys.exit(1)

    crawler.start()
    if Spider.closed_reason is None or isinstance(Spider.closed_reason, int):
        sys.exit(1)
