# Gruvi example program: echo server, using StreamServer

import logging
import gruvi

def echo_handler(stream, transport, protocol):
    peer = transport.get_extra_info('peername')
    print('New connection from {}'.format(gruvi.saddr(peer)))
    while True:
        buf = stream.read1()
        if not buf:
            break
        stream.write(buf)
    print('Connection lost')

server = gruvi.StreamServer(echo_handler)
server.listen(('localhost', 7777))
for addr in server.addresses:
    print('Listen on {}'.format(gruvi.saddr(addr)))

try:
    gruvi.get_hub().switch()
except KeyboardInterrupt:
    print('Exiting on CTRL-C')
