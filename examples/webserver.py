#!/usr/bin/env python
#
# Example: hello world web server

from __future__ import print_function

import logging
import argparse

from gruvi import get_hub
from gruvi.http import HttpServer

logging.basicConfig()

parser = argparse.ArgumentParser()
parser.add_argument('hostname');
parser.add_argument('port', type=int);
args = parser.parse_args()


def hello_app(environ, start_response):
    headers = [('Content-Type', 'text/plain')]
    start_response('200 OK', headers)
    return [b'Hello, world!']


server = HttpServer(hello_app)
server.listen((args.hostname, args.port))

hub = get_hub()
print('Press CTRL-C to exit')
hub.switch(interrupt=True)
