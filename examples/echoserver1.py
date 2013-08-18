# Example: echo server, using StreamServer

import logging
import argparse

from gruvi import get_hub, util
from gruvi.stream import StreamServer

logging.basicConfig()

parser = argparse.ArgumentParser()
parser.add_argument('port', type=int)
args = parser.parse_args()

def echo_handler(stream, protocol, client):
    peer = client.getpeername()
    print('Connection from {0}'.format(util.saddr(peer)))
    while True:
        buf = stream.read(4096)
        if not buf:
            break
        stream.write(buf)
    print('Connection closed')

server = StreamServer(echo_handler)
server.listen(('0.0.0.0', args.port))

hub = get_hub()
hub.switch(interrupt=True)
