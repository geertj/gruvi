#
# This file is part of gruvi. Gruvi is free software available under the terms
# of the MIT license. See the file "LICENSE" that was provided together with
# this source file for the licensing terms.
#
# Copyright (c) 2012 the gruvi authors. See the file "AUTHORS" for a complete
# list.

import gruvi.test
import subprocess


class TestSSL(gruvi.test.UnitTest):

    @classmethod
    def setup_class(cls):
        super(TestSSL, cls).setup_class()
        # Create a new key and a self signed certificate for it
        fname = cls.tempname('server.pem')
        try:
            proc = subprocess.Popen(['openssl', 'req', '-new', '-newkey', 'rsa:1024',
                        '-x509', '-subj', '/CN=test/', '-days', '365', '-nodes',
                        '-batch', '-out', fname, '-keyout', fname],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            raise gruvi.test.SkipTest('openssl is required for this test')
        stdout, stderr = proc.communicate()
        if proc.returncode:
            raise gruvi.test.SkipTest('failed to create a certificate')
        cls.keyfile = cls.certfile = fname

    def test_echo(self):
        hub = gruvi.Hub.get()
        s1 = gruvi.Socket(hub)
        s1.bind(('localhost', 0))
        s1.listen(1)
        s2 = gruvi.Socket(hub)
        data = [b'foo', None]
        def server(sock):
            csock, addr = sock.accept()
            sslsock = gruvi.SSLSocket(hub, csock, server_side=True,
                            keyfile=self.keyfile, certfile=self.certfile)
            assert isinstance(sslsock, gruvi.SSLSocket)
            buf = sslsock.recv()
            sslsock.send(buf)
            sslsock.close()
        def client(sock, addr):
            sock.connect(addr)
            sslsock = gruvi.SSLSocket(hub, sock)
            sslsock.send(data[0])
            data[1] = sslsock.recv()
            sslsock.close()
        gr1 = gruvi.Greenlet(hub)
        gr1.start(server, s1)
        gr2 = gruvi.Greenlet(hub)
        gr2.start(client, s2, s1.getsockname())
        hub.switch()
        assert data[0] == data[1]

    def test_wrap_unwrap(self):
        hub = gruvi.Hub.get()
        s1 = gruvi.Socket(hub)
        s1.bind(('localhost', 0))
        s1.listen(1)
        s2 = gruvi.Socket(hub)
        data = [b'foo', b'bar', b'baz']
        echo = []
        def server(sock):
            csock, addr = sock.accept()
            buf = csock.recv(3)
            csock.send(buf)
            sslsock = gruvi.SSLSocket(hub, csock, server_side=True,
                            keyfile=self.keyfile, certfile=self.certfile)
            assert isinstance(sslsock, gruvi.SSLSocket)
            buf = sslsock.recv(3)
            sslsock.send(buf)
            uwsock = sslsock.unwrap()
            assert uwsock is csock
            buf = uwsock.recv(3)
            uwsock.send(buf)
        def client(sock, addr):
            sock.connect(addr)
            sock.send(data[0])
            echo.append(sock.recv(3))
            sslsock = gruvi.SSLSocket(hub, sock)
            sslsock.send(data[1])
            echo.append(sslsock.recv(3))
            uwsock = sslsock.unwrap()
            assert uwsock is sock
            sock.send(data[2])
            echo.append(sock.recv(3))
        gr1 = gruvi.Greenlet(hub)
        gr1.start(server, s1)
        gr2 = gruvi.Greenlet(hub)
        gr2.start(client, s2, s1.getsockname())
        hub.switch()
        assert data == echo

    def test_send_lots_of_data(self):
        hub = gruvi.Hub.get()
        s1 = gruvi.Socket(hub)
        s1.bind(('localhost', 0))
        s1.listen(1)
        s2 = gruvi.Socket(hub)
        counters = [0, 0]
        buf = b'x' * 10000
        def server(sock):
            csock, addr = sock.accept()
            sslsock = gruvi.SSLSocket(hub, csock, server_side=True,
                            keyfile=self.keyfile, certfile=self.certfile)
            while True:
                buf = sslsock.recv()
                if len(buf) == 0:
                    break
                counters[1] += len(buf)
            sslsock.close()
        def client(sock, addr):
            sock.connect(addr)
            sslsock = gruvi.SSLSocket(hub, sock)
            for i in range(1000):
                nbytes = sslsock.send(buf)
                counters[0] += nbytes
            sslsock.close()
        gr1 = gruvi.Greenlet(hub)
        gr1.start(server, s1)
        gr2 = gruvi.Greenlet(hub)
        gr2.start(client, s2, s1.getsockname())
        hub.switch()
        assert counters[0] == counters[1]
