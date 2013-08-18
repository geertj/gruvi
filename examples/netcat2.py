#!/usr/bin/env python
#
# Example: a simple nc(1), client only, using the stream client and greenlets.

from __future__ import absolute_import, print_function

import sys
import argparse
import logging

import pyuv
from gruvi import get_hub, util
from gruvi.pyuv import TTY
from gruvi.stream import StreamClient

logging.basicConfig()

parser = argparse.ArgumentParser()
parser.add_argument('hostname')
parser.add_argument('port', type=int)
args = parser.parse_args()

client = StreamClient()
client.connect((args.hostname, args.port))
peer = client.transport.getpeername()
print('Connected to {0!s}'.format(util.saddr(peer)), file=sys.stderr)

stdin = StreamClient()
stdin.connect(TTY(sys.stdin))
stdout = StreamClient()
stdout.connect(TTY(sys.stdout))


def read_stdin():
    while True:
        buf = stdin.read(4096)
        if not buf:
            logger.debug('Got EOF on stdin')
            client.shutdown()
            break
        client.write(buf)

def read_network():
    while True:
        buf = client.read(4096)
        if not buf:
            logger.debug('Connection closed by peer')
            break
        stdout.write(buf)
    hub.parent.switch()


stdin_reader = gruvi.Greenlet(read_stdin)
stdin_reader.start()
network_reader = gruvi.Greenlet(read_network)
network_reader.start()

hub = get_hub()
print('Press CTRL-C to quit (CTRL-D to send EOF)', file=sys.stderr)
hub.switch(interrupt=True)
