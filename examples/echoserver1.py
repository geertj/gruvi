# Gruvi example program: echo server, using StreamServer

import gruvi

def echo_handler(stream, transport, protocol):
    peer = transport.get_extra_info('peername')
    print('New connection from {0}'.format(gruvi.saddr(peer)))
    while True:
        buf = stream.read1()
        if not buf:
            break
        stream.write(buf)
    print('Connection lost')

server = gruvi.StreamServer(echo_handler)
server.listen(('localhost', 0))
for addr in server.addresses:
    print('Listen on {0}'.format(gruvi.saddr(addr)))

server.run()
