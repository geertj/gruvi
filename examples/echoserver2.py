#!/usr/bin/env python
#
# Example: echo server, using a new protocol

from __future__ import print_function

import logging
import argparse

import pyuv
from gruvi import switchpoint, get_hub, util
from gruvi.protocols import Protocol

logging.basicConfig()


class EchoServer(Protocol):
    """Echo protocol server."""

    def _on_transport_readable(self, transport, data, error):
        if error == pyuv.errno.UV_EOF:
            self._logger.debug('got EOF from client')
            self._close_transport(transport)
        elif error:
            self._logger.error('got error {0} from client', error)
            self._close_transport(transport)
        else:
            transport.write(data)

    @switchpoint
    def listen(self, address, ssl=False, **transport_args):
        super(EchoServer, self)._listen(address, ssl, **transport_args)


parser = argparse.ArgumentParser()
parser.add_argument('hostname');
parser.add_argument('port', type=int)
args = parser.parse_args()

server = EchoServer()
server.listen((args.hostname, args.port))
addr = server.transport.getsockname()
print('Listening on {0}'.format(util.saddr(addr)))

hub = get_hub()
print('Press CTRL-C to quit')
hub.switch(interrupt=True)
