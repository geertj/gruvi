#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import print_function, absolute_import

import os
import time
from nose import SkipTest
from nose.tools import assert_raises

import gruvi
from gruvi.ssl import SSLPipe, SSL
from gruvi.test import UnitTest
from gruvi.stream import StreamClient, StreamServer


def communicate(buf, client, server, clientssl, serverssl):
    """Send *buf* from *client* to *server*.
    
    The *clientssl* and *serverssl* arguments are potentially empty list of
    initial SSL data. The clientssl list is SSL data from the client to send to
    the server, the serverssl list is SSL data to send from the server to the
    client.
    
    The data that is received on the server is returned.
    """
    received = []
    offset = bytes_received = 0
    initial_serverssl = serverssl
    while bytes_received != len(buf):
        serverssl, appdata = server.feed_ssldata(b''.join(clientssl))
        if initial_serverssl:
            serverssl = initial_serverssl + serverssl
            initial_serverssl = None
        for data in appdata:
            assert len(data) > 0
            bytes_received += len(data)
        received.extend(appdata)
        clientssl, appdata = client.feed_ssldata(b''.join(serverssl))
        for data in appdata:
            assert len(data) == 0
        if offset != len(buf):
            ssldata, offset = client.feed_appdata(buf, offset)
            clientssl.extend(ssldata)
    received = b''.join(received)
    return received


class TestSSLPipe(UnitTest):
    """Test suite for the (internal) SSLPipe class."""

    @classmethod
    def setup_class(cls):
        super(TestSSLPipe, cls).setup_class()
        if not cls.certname:
            raise SkipTest('no certificate available')

    def test_wrapped(self):
        client = SSLPipe(server_side=False)
        server = SSLPipe(server_side=True, keyfile=self.certname,
                         certfile=self.certname)
        buf = b'x' * 1000
        # start client handshake
        clientssl = client.start_handshake()
        assert len(clientssl) == 1
        assert len(clientssl[0]) > 0  # client initiates
        serverssl = server.start_handshake()
        assert len(serverssl) == 0  # server waits
        received = communicate(buf, client, server, clientssl, serverssl)
        assert received == buf

    def test_shutdown(self):
        client = SSLPipe(server_side=False)
        server = SSLPipe(server_side=True, keyfile=self.certname,
                         certfile=self.certname)
        buf = b'x' * 1000
        # start client handshake
        clientssl = client.start_handshake()
        serverssl = server.start_handshake()
        received = communicate(buf, client, server, clientssl, serverssl)
        assert received == buf
        # the client initiates a shutdown
        clientssl = client.start_shutdown()
        assert len(clientssl) == 1
        assert len(clientssl[0]) > 0  # the c->s close_notify alert
        # communicate the close_notify to the server
        serverssl, appdata = server.feed_ssldata(clientssl[0])
        assert len(serverssl) == 1
        assert len(serverssl[0]) > 0  # the s->c close_notify
        assert len(appdata) == 0
        assert server.state == SSLPipe.s_unwrapped
        # send back the server response to the client
        clientssl, appdata = client.feed_ssldata(serverssl[0])
        assert len(clientssl) == 0
        assert len(appdata) == 0
        assert client.state == SSLPipe.s_unwrapped

    def test_unwrapped(self):
        client = SSLPipe()
        server = SSLPipe()
        buf = b'x' * 1000
        received = communicate(buf, client, server, [], [])
        assert received == buf

    def test_unwrapped_after_wrapped(self):
        client = SSLPipe(server_side=False)
        server = SSLPipe(server_side=True, keyfile=self.certname,
                         certfile=self.certname)
        buf = b'x' * 1000
        # send some data in the clear
        received = communicate(buf, client, server, [], [])
        assert received == buf
        # now start the handshake and send some encrypted data
        clientssl = client.start_handshake()
        server.start_handshake()
        received = communicate(buf, client, server, clientssl, [])
        assert received == buf
        # move back to clear again
        clientssl = client.start_shutdown()
        received = communicate(buf, client, server, clientssl, [])
        assert received == buf
        # and back to encrypted again..
        clientssl = client.start_handshake()
        server.start_handshake()
        received = communicate(buf, client, server, clientssl, [])
        assert received == buf

    def test_simultaneous_shutdown(self):
        client = SSLPipe(server_side=False)
        server = SSLPipe(server_side=True, keyfile=self.certname,
                         certfile=self.certname)
        buf = b'x' * 1000
        # start an encrypted session
        clientssl = client.start_handshake()
        server.start_handshake()
        received = communicate(buf, client, server, clientssl, [])
        assert received == buf
        # tear it down concurrently
        clientssl = client.start_shutdown()
        serverssl = server.start_shutdown()
        received = communicate(buf, client, server, clientssl, serverssl)
        assert client.state == SSLPipe.s_unwrapped
        assert server.state == SSLPipe.s_unwrapped
        assert received == buf  # this was sent in the clear

    def test_speed(self):
        server = SSLPipe(keyfile=self.certname, certfile=self.certname,
                         server_side=True)
        client = SSLPipe(server_side=False)
        buf = b'x' * 65536
        nbytes = 0
        clientssl = client.start_handshake()
        server.start_handshake()
        t1 = time.time()
        while (time.time() - t1) < 1:
            received = communicate(buf, client, server, clientssl, [])
            if clientssl:
                clientssl = []
            nbytes += len(received)
        t2 = time.time()
        speed = (nbytes / (t2 - t1)) / (1024 * 1024)
        print('SSL speed: {0:.2f} MiB/sec'.format(speed))


class TestSSL(UnitTest):

    @classmethod
    def setup_class(cls):
        super(TestSSL, cls).setup_class()
        if not cls.certname:
            raise SkipTest('no certificate available')

    def test_read_write(self):
        nbytes = [0]
        cipher = [None]
        received = []
        buf = b'x' * 1000
        def make_ssl_client(transport, error):
            serverssl = gruvi.ssl.SSL(server_side=True, keyfile=self.certname,
                                      certfile=self.certname,
                                      do_handshake_on_connect=False)
            transport.accept(serverssl)
            serverssl.do_handshake(server_handshake_complete)
        def server_handshake_complete(transport, error):
            cipher[0] = transport.ssl.cipher()
            transport.start_read(server_read)
        def server_read(transport, data, error):
            if error:
                transport.close()
                return
            nbytes[0] += len(data)
            received.append(data)
        def client_write(transport, error):
            if error:
                return
            transport.write(buf)
            transport.close()
        lsock = gruvi.pyuv.TCP()
        lsock.bind(('127.0.0.1', 0))
        # do not keep the hub loop busy with the listen socket.
        lsock.unref()
        addr = lsock.getsockname()
        lsock.listen(make_ssl_client)
        clientssl = gruvi.ssl.SSL()
        clientssl.connect(addr, client_write)
        hub = gruvi.Hub.get()
        hub.switch()
        assert nbytes[0] == len(buf)
        assert b''.join(received) == buf
        assert len(cipher[0]) == 3
        print('Cipher: {0}'.format(cipher[0][0]))

    def test_handshake_unwrap(self):
        nbytes = [0]
        received = []
        buf_clear = b'x' * 1000
        buf_ssl = b'y' * 1000
        ciphers = []
        transports = []
        def make_ssl_client(transport, error):
            serverssl = gruvi.ssl.SSL(server_side=True, keyfile=self.certname,
                                      certfile=self.certname,
                                      do_handshake_on_connect=False)
            transport.accept(serverssl)
            serverssl.start_read(server_read)
            transports.append(serverssl)  # don't let the GC collect it
        def server_read(transport, data, error):
            if error:
                transport.close()
                return
            nbytes[0] += len(data)
            received.append(data)
            if nbytes[0] == len(buf_clear):
                transport.write(b'x')  # invite client to start handshake
                transport.do_handshake()
        def on_client_connect(transport, error):
            transports.append(transport)
            if error:
                transport.close()
                return
            transport.write(buf_clear)
            transport.start_read(client_read)
        def client_read(transport, data, error):
            if error:
                transport.close()
                return
            transport.stop_read()
            ciphers.append(transport.ssl)
            transport.do_handshake(client_write_ssl)
        def client_write_ssl(transport, error):
            transport.write(buf_ssl)
            ciphers.append(transport.ssl.cipher())
            transport.unwrap(client_unwrap)
        def client_unwrap(transport, error):
            transport.write(buf_clear)
            ciphers.append(transport.ssl)
            transport.shutdown(lambda h,e: transport.close())
        lsock = gruvi.pyuv.TCP()
        lsock.bind(('127.0.0.1', 0))
        lsock.unref()
        addr = lsock.getsockname()
        lsock.listen(make_ssl_client)
        clientssl = gruvi.ssl.SSL(do_handshake_on_connect=False)
        clientssl.connect(addr, on_client_connect)
        hub = gruvi.Hub.get()
        hub.switch()
        assert nbytes[0] == 2*len(buf_clear) + len(buf_ssl)
        assert b''.join(received) == buf_clear + buf_ssl + buf_clear
        assert len(ciphers) == 3
        assert ciphers[0] is None
        assert len(ciphers[1]) == 3
        assert ciphers[2] is None

    def test_stream(self):
        def echo_handler(stream, protocol, client):
            while True:
                buf = stream.read(4096)
                if not buf:
                    break
                nbytes = stream.write(buf)
        server = StreamServer(echo_handler)
        server.listen(('localhost', 0), ssl=True,
                      keyfile=self.certname, certfile=self.certname)
        addr = server.transport.getsockname()
        client = StreamClient()
        client.connect(addr, ssl=True)
        buf = b'x' * 1024
        client.write(buf)
        result = b''
        while len(result) != 1024:
            result += client.read(1024)
        assert result == buf
        client.close()
        server.close()
