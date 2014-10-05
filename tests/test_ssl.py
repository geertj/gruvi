#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import print_function, absolute_import

import os
import ssl
import socket
import unittest
import pyuv

from unittest import SkipTest

from gruvi.ssl import SslPipe, SslTransport
from gruvi.sslcompat import SSLContext
from support import UnitTest
from test_transports import EventLoopTest, TransportTest


def communicate(buf, client, server, clientssl, serverssl):
    """Send *buf* from *client* to *server* over SSL.

    The *clientssl* and *serverssl* arguments are potentially empty list of
    initial SSL data. The clientssl list is SSL data from the client to send to
    the server, the serverssl list is SSL data to send from the server to the
    client.

    The data that is received on the server is returned.
    """
    received = []
    offset = bytes_received = 0
    while True:
        ssldata, appdata = server.feed_ssldata(b''.join(clientssl))
        serverssl += ssldata
        received += appdata
        for chunk in appdata:
            if not chunk:
                break  # close_notify
            bytes_received += len(chunk)
        clientssl = []
        ssldata, appdata = client.feed_ssldata(b''.join(serverssl))
        clientssl += ssldata
        for chunk in appdata:
            assert len(chunk) == 0
        serverssl = []
        ssldata, offset = client.feed_appdata(buf, offset)
        clientssl += ssldata
        if not clientssl and not serverssl:
            break
    received = b''.join(received)
    return received


class TestSslPipe(UnitTest):
    """Test suite for the SslPipe class."""

    def setUp(self):
        if not os.access(self.certname, os.R_OK):
            raise SkipTest('no certificate available')
        super(TestSslPipe, self).setUp()
        context = SSLContext(ssl.PROTOCOL_SSLv23)
        context.load_cert_chain(self.certname, self.certname)
        self.client = SslPipe(context, False)
        self.server = SslPipe(context, True)

    def test_wrapped(self):
        # Send a simple chunk of data over SSL from client to server.
        buf = b'x' * 1000
        client, server = self.client, self.server
        # The client starts the handshake.
        clientssl = client.do_handshake()
        self.assertEqual(len(clientssl), 1)
        self.assertGreater(len(clientssl[0]), 0)
        # The server waits.
        serverssl = server.do_handshake()
        self.assertEqual(len(serverssl), 0)
        received = communicate(buf, client, server, clientssl, serverssl)
        self.assertTrue(client.wrapped)
        self.assertTrue(server.wrapped)
        self.assertEqual(received, buf)

    def test_echo(self):
        # Send a chunk from client to server and echo it back.
        buf = b'x' * 1000
        client, server = self.client, self.server
        clientssl = client.do_handshake()
        serverssl = server.do_handshake()
        received = communicate(buf, client, server, clientssl, serverssl)
        self.assertEqual(received, buf)
        received = communicate(buf, server, client, [], [])
        self.assertEqual(received, buf)

    def test_shutdown(self):
        # Test a clean shutdown of the SSL protocol.
        client, server = self.client, self.server
        buf = b'x' * 1000
        clientssl = client.do_handshake()
        serverssl = server.do_handshake()
        received = communicate(buf, client, server, clientssl, serverssl)
        self.assertEqual(received, buf)
        # The client initiates a shutdown.
        clientssl = client.shutdown()
        self.assertEqual(len(clientssl), 1)
        self.assertGreater(len(clientssl[0]), 0)  # the c->s close_notify alert
        # Communicate the close_notify to the server.
        serverssl, appdata = server.feed_ssldata(clientssl[0])
        # b'' means close notify: acknowledge it
        self.assertEqual(serverssl, [])
        self.assertEqual(appdata, [b''])
        serverssl = server.shutdown()
        # Now we should have a close_notify
        self.assertEqual(len(serverssl), 1)
        self.assertGreater(len(serverssl[0]), 0)  # the s->c close_notify
        self.assertEqual(appdata, [b''])
        self.assertFalse(server.wrapped)
        # Send back the server response to the client.
        clientssl, appdata = client.feed_ssldata(serverssl[0])
        self.assertEqual(clientssl, [])
        self.assertEqual(appdata, [b''])
        self.assertFalse(client.wrapped)

    def test_unwrapped(self):
        # Send data over an unencrypted channel.
        client, server = self.client, self.server
        buf = b'x' * 1000
        received = communicate(buf, client, server, [], [])
        self.assertEqual(received, buf)

    def test_unwrapped_after_wrapped(self):
        # Send data over SSL, then unwrap, and send data in the clear.
        client, server = self.client, self.server
        buf = b'x' * 1000
        # Send some data in the clear.
        received = communicate(buf, client, server, [], [])
        self.assertEqual(received, buf)
        # Now start the handshake and send some encrypted data.
        clientssl = client.do_handshake()
        server.do_handshake()
        received = communicate(buf, client, server, clientssl, [])
        self.assertTrue(client.wrapped)
        self.assertTrue(server.wrapped)
        self.assertEqual(received, buf)
        # Move back to clear again.
        clientssl = client.shutdown()
        received = communicate(buf, client, server, clientssl, [])
        self.assertEqual(received, b'')
        serverssl = server.shutdown()
        received = communicate(buf, client, server, [], serverssl)
        self.assertFalse(client.wrapped)
        self.assertFalse(server.wrapped)
        self.assertEqual(received, buf)
        # And back to encrypted again..
        clientssl = client.do_handshake()
        server.do_handshake()
        received = communicate(buf, client, server, clientssl, [])
        self.assertTrue(client.wrapped)
        self.assertTrue(server.wrapped)
        self.assertEqual(received, buf)

    def test_simultaneous_shutdown(self):
        # Test a simultaenous shutdown.
        client, server = self.client, self.server
        buf = b'x' * 1000
        # Start an encrypted session.
        clientssl = client.do_handshake()
        server.do_handshake()
        received = communicate(buf, client, server, clientssl, [])
        self.assertEqual(received, buf)
        # Tear it down concurrently.
        clientssl = client.shutdown()
        serverssl = server.shutdown()
        received = communicate(buf, client, server, clientssl, serverssl)
        self.assertFalse(client.wrapped)
        self.assertFalse(server.wrapped)
        self.assertEqual(received, buf)  # this was sent in the clear


class SslTransportTest(TransportTest):

    def setUp(self):
        if not os.access(self.certname, os.R_OK):
            raise SkipTest('no certificate available')
        super(SslTransportTest, self).setUp()
        self.context = SSLContext(ssl.PROTOCOL_SSLv3)
        self.context.load_cert_chain(self.certname, self.certname)

    def create_transport(self, handle, protocol, server_side):
        transport = SslTransport(handle, self.context, server_side)
        transport.start(protocol)
        return transport


class TestSslTcpTransport(SslTransportTest, EventLoopTest):

    def create_handle(self):
        return pyuv.TCP(self.loop)

    def bind_handle(self, handle):
        host = socket.gethostbyname('localhost')
        handle.bind((host, 0))
        return handle.getsockname()


class TestSslPipeTransport(SslTransportTest, EventLoopTest):

    def create_handle(self):
        return pyuv.Pipe(self.loop)

    def bind_handle(self, handle):
        addr = self.pipename('test-pipe')
        handle.bind(addr)
        return addr


if __name__ == '__main__':
    unittest.main()
