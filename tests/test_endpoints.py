#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import socket
import unittest

import gruvi
from gruvi.stream import StreamProtocol
from gruvi.endpoints import create_server, create_connection, getaddrinfo
from gruvi.transports import TransportError

from support import UnitTest


class TestCreateConnection(UnitTest):

    def test_tcp(self):
        # Ensure that create_connection() and create_server() can be used to
        # connect to each other over TCP.
        server = create_server(StreamProtocol, ('localhost', 0))
        addr = server.addresses[0]
        ctrans, cproto = create_connection(StreamProtocol, addr)
        gruvi.sleep(0.1)  # allow Server to accept()
        strans, sproto = list(server.connections)[0]
        cproto.stream.write(b'foo\n')
        self.assertEqual(sproto.stream.readline(), b'foo\n')
        server.close()
        self.assertEqual(len(list(server.connections)), 0)
        self.assertEqual(cproto.stream.readline(), b'')
        ctrans.close()

    def test_pipe(self):
        # Ensure that create_connection() and create_server() can be used to
        # connect to each other over a pipe.
        addr = self.pipename()
        server = create_server(StreamProtocol, addr)
        ctrans, cproto = create_connection(StreamProtocol, addr)
        gruvi.sleep(0.1)  # allow Server to accept()
        strans, sproto = list(server.connections)[0]
        cproto.stream.write(b'foo\n')
        self.assertEqual(sproto.stream.readline(), b'foo\n')
        server.close()
        self.assertEqual(len(list(server.connections)), 0)
        self.assertEqual(cproto.stream.readline(), b'')
        ctrans.close()

    def test_tcp_ssl(self):
        # Ensure that create_connection() and create_server() can be used to
        # connect to each other over TCP using SSL.
        context = self.get_ssl_context()
        server = create_server(StreamProtocol, ('localhost', 0), ssl=context)
        addr = server.addresses[0]
        ctrans, cproto = create_connection(StreamProtocol, addr, ssl=context)
        # No need to sleep here because create_connection waits for the SSL
        # handshake to complete
        strans, sproto = list(server.connections)[0]
        cproto.stream.write(b'foo\n')
        self.assertEqual(sproto.stream.readline(), b'foo\n')
        server.close()
        self.assertEqual(len(list(server.connections)), 0)
        self.assertEqual(cproto.stream.readline(), b'')
        ctrans.close()

    def test_pipe_ssl(self):
        # Ensure that create_connection() and create_server() can be used to
        # connect to each other over a pipe using SSL.
        context = self.get_ssl_context()
        addr = self.pipename()
        server = create_server(StreamProtocol, addr, ssl=context)
        ctrans, cproto = create_connection(StreamProtocol, addr, ssl=context)
        # No need to sleep here because create_connection waits for the SSL
        # handshake to complete
        strans, sproto = list(server.connections)[0]
        cproto.stream.write(b'foo\n')
        self.assertEqual(sproto.stream.readline(), b'foo\n')
        server.close()
        self.assertEqual(len(list(server.connections)), 0)
        self.assertEqual(cproto.stream.readline(), b'')
        ctrans.close()

    def test_ssl_handshake_on_connect(self):
        # Ensure that when create_connection(ssl=True) returns, that the SSL
        # handshake has completed.
        context = self.get_ssl_context()
        server = create_server(StreamProtocol, ('localhost', 0), ssl=context)
        addr = server.addresses[0]
        ctrans, cproto = create_connection(StreamProtocol, addr, ssl=context)
        # The SSL handshake should be completed at this point. This means that
        # there should be a channel binding.
        sslobj = ctrans.get_extra_info('ssl')
        self.assertIsNotNone(sslobj)
        sslcb = sslobj.get_channel_binding('tls-unique')
        self.assertGreater(len(sslcb), 0)
        strans, sproto = list(server.connections)[0]
        cproto.stream.write(b'foo\n')
        self.assertEqual(sproto.stream.readline(), b'foo\n')
        server.close()
        self.assertEqual(len(list(server.connections)), 0)
        self.assertEqual(cproto.stream.readline(), b'')
        ctrans.close()

    def test_ssl_no_handshake_on_connect(self):
        # Ensure that when create_connection(ssl=True) returns, that the SSL
        # handshake has completed.
        context = self.get_ssl_context()
        server = create_server(StreamProtocol, ('localhost', 0), ssl=context)
        addr = server.addresses[0]
        ssl_args = {'do_handshake_on_connect': False}
        ctrans, cproto = create_connection(StreamProtocol, addr, ssl=context, ssl_args=ssl_args)
        # The SSL handshake has not been established at this point.
        sslobj = ctrans.get_extra_info('ssl')
        self.assertIsNone(sslobj)
        # Now initiate the SSL handshake and allow it some time to complete
        ctrans.do_handshake()
        gruvi.sleep(0.1)
        # There should be a channel binding now.
        sslobj = ctrans.get_extra_info('ssl')
        self.assertIsNotNone(sslobj)
        sslcb = sslobj.get_channel_binding('tls-unique')
        self.assertGreater(len(sslcb), 0)
        strans, sproto = list(server.connections)[0]
        cproto.stream.write(b'foo\n')
        self.assertEqual(sproto.stream.readline(), b'foo\n')
        server.close()
        self.assertEqual(len(list(server.connections)), 0)
        self.assertEqual(cproto.stream.readline(), b'')
        ctrans.close()

    def test_tcp_connection_refused(self):
        # Ensure that create_connection raises an exception when connecting to
        # a TCP port where there is no listener.
        server = create_server(StreamProtocol, ('localhost', 0))
        addr = server.addresses[0]
        server.close()
        self.assertRaises(TransportError, create_connection, StreamProtocol, addr)

    def test_pipe_connection_refused(self):
        # Ensure that create_connection raises an exception when connecting to
        # a Pipe that has no listener.
        addr = self.pipename()
        self.assertRaises(TransportError, create_connection, StreamProtocol, addr)


class TestGetAddrInfo(UnitTest):

    def test_resolve(self):
        res = getaddrinfo('localhost', family=socket.AF_INET)
        self.assertIsInstance(res, list)
        self.assertGreater(len(res), 0)
        self.assertEqual(res[0].sockaddr, ('127.0.0.1', 0))

    def get_resolve_timeout(self):
        self.assertRaises(gruvi.Timeout, getaddrinfo, 'localhost', timeout=0)


if __name__ == '__main__':
    unittest.main()
