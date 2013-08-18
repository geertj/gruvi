#!/usr/bin/env python
#
# Example: a simple nc(1), client only, using the transport API.
# Also shows how to use asynchronous IO with stdin/stdout

from __future__ import absolute_import, print_function

import sys
import argparse
import logging

import pyuv
from gruvi import get_hub, create_connection, saddr
from gruvi.pyuv import TTY

logging.basicConfig()

parser = argparse.ArgumentParser()
parser.add_argument('hostname')
parser.add_argument('port', type=int)
args = parser.parse_args()

conn = util.create_connection((args.hostname, args.port))
peer = conn.getpeername()
print('Connected to {0!s}'.format(util.saddr(peer)), file=sys.stderr)
stdin = TTY(sys.stdin)
stdout = TTY(sys.stdout)


def read_stdin(handle, data, error):
    if error == pyuv.errno.UV_EOF:
        logger.debug('Got EOF from stdin')
        conn.shutdown()
    elif error:
        logger.error('Error {0} in read_stdin()'.format(error))
        hub.parent.switch()
    else:
        conn.write(data)

def read_network(handle, data, error):
    if error == pyuv.errno.UV_EOF:
        logger.debug('Peer closed connection')
        hub.parent.switch()
    elif error:
        logger.error('Error {0} in read_network()'.format(error))
        hub.parent.switch()
    else:
        stdout.write(data)


stdin.start_read(read_stdin)
conn.start_read(read_network)

hub = get_hub()
print('Press CTRL-C to quit (CTRL-D to send EOF)', file=sys.stderr)
hub.switch(interrupt=True)
