#!/usr/bin/env python

import sys
import gruvi


class EchoServer(gruvi.Greenlet):

    def __init__(self, hub, address, handler):
        super(EchoServer, self).__init__(hub)
        self.handler = handler
        self.sock = gruvi.Socket(hub)
        self.sock.bind(address)
        self.sock.listen(100)
        self.address = self.sock.getsockname()
        sys.stdout.write('listing on %s:%d\n' % self.address)

    def run(self):
        while True:
            conn, addr = self.sock.accept()
            handler = self.handler(self.hub, conn, addr)
            handler.start()


class EchoHandler(gruvi.Greenlet):

    def __init__(self, hub, conn, addr):
        super(EchoHandler, self).__init__(hub)
        self.conn = conn
        self.address = addr

    def run(self):
        sys.stdout.write('START client %s:%d\n' % self.address)
        while True:
            buf = self.conn.recv()
            if buf == '':
                break
            self.conn.sendall(buf)
        self.conn.close()
        sys.stdout.write('DONE client %s:%d\n' % self.address)


hub = gruvi.Hub.get()
server = EchoServer(hub, ('localhost', 0), EchoHandler)
server.start()
hub.switch()
