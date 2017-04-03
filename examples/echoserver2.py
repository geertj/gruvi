# Gruvi example program: an echo server, using a Protocol

import gruvi

class EchoProtocol(gruvi.Protocol):

    def connection_made(self, transport):
        self._transport = transport
        peer = transport.get_extra_info('peername')
        print('New connection from {0}'.format(gruvi.saddr(peer)))

    def data_received(self, data):
        self._transport.write(data)

    def eof_received(self):
        print('Connection lost')

server = gruvi.create_server(EchoProtocol, ('localhost', 0))
for addr in server.addresses:
    print('Listen on {0}'.format(gruvi.saddr(addr)))

server.run()
