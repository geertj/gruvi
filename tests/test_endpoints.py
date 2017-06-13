#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import ssl
import socket
import unittest
import pyuv
from unittest import SkipTest

import gruvi
from gruvi.hub import switchpoint, get_hub
from gruvi.stream import StreamProtocol
from gruvi.endpoints import create_server, create_connection, getaddrinfo
from gruvi.endpoints import Client, Server
from gruvi.transports import TransportError
from gruvi.protocols import Protocol
from gruvi.sync import Queue
from gruvi.util import delegate_method
from gruvi.fibers import spawn

from support import UnitTest, socketpair


class StreamProtocolNoSslHandshake(StreamProtocol):

    def connection_made(self, transport):
        transport._do_handshake_on_connect = False
        super(StreamProtocolNoSslHandshake, self).connection_made(transport)


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
        server = create_server(StreamProtocol, ('localhost', 0), **self.ssl_s_args)
        addr = server.addresses[0]
        ctrans, cproto = create_connection(StreamProtocol, addr, **self.ssl_c_args)
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
        addr = self.pipename()
        server = create_server(StreamProtocol, addr, **self.ssl_s_args)
        ctrans, cproto = create_connection(StreamProtocol, addr, **self.ssl_cp_args)
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
        server = create_server(StreamProtocol, ('localhost', 0), **self.ssl_s_args)
        addr = server.addresses[0]
        ctrans, cproto = create_connection(StreamProtocol, addr, **self.ssl_c_args)
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
        server = create_server(StreamProtocol, ('localhost', 0), **self.ssl_s_args)
        addr = server.addresses[0]
        ctrans, cproto = create_connection(StreamProtocolNoSslHandshake, addr, **self.ssl_c_args)
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

    def test_tcp_ssl_certificate_error(self):
        # Ensure that create_connection() raises a CertificateError if the
        # certificate doesn't validate.
        if not hasattr(ssl, 'create_default_context'):
            raise SkipTest('Certificate validation not supported')
        server = create_server(StreamProtocol, ('localhost', 0), **self.ssl_s_args)
        addr = server.addresses[0]
        ssl_args = self.ssl_c_args.copy()
        ssl_args['server_hostname'] = 'foobar'
        self.assertRaises(TransportError, create_connection, StreamProtocol, addr, **ssl_args)
        server.close()


class TestGetAddrInfo(UnitTest):

    def test_resolve(self):
        res = getaddrinfo('localhost', family=socket.AF_INET)
        self.assertIsInstance(res, list)
        self.assertGreater(len(res), 0)
        self.assertEqual(res[0].sockaddr, ('127.0.0.1', 0))

    def get_resolve_timeout(self):
        self.assertRaises(gruvi.Timeout, getaddrinfo, 'localhost', timeout=0)


class IpcProtocol(Protocol):
    """A very simple line based protocol that is used to test passing file
    descriptors."""

    def __init__(self, server=None, server_context=None):
        self._server = server
        self._server_context = server_context
        self._queue = Queue()
        self._transport = None

    @property
    def transport(self):
        return self._transport

    def connection_made(self, transport):
        self._transport = transport
        self._buffer = b''

    def data_received(self, data):
        self._buffer += data
        p0 = p1 = 0
        while True:
            p1 = self._buffer.find(b'\n', p0)
            if p1 == -1:
                break
            command = self._buffer[p0:p1].decode('ascii')
            self.command_received(command)
            p0 = p1+1
        if p0:
            self._buffer = self._buffer[p0:]

    def command_received(self, command):
        if self._server is None:
            self._queue.put(command)
        elif command == 'handle':
            handle = self._transport.get_extra_info('handle')
            assert handle is not None
            self._server.accept_connection(handle)
            self.send('ok')
        elif command == 'ssl_handle':
            handle = self._transport.get_extra_info('handle')
            assert handle is not None
            self._server.accept_connection(handle, ssl=self._server_context)
            self.send('ok')
        elif command == 'ping':
            self.send('pong')
        elif command == 'type':
            handle = self._transport.get_extra_info('handle')
            assert handle is not None
            htype = 'tcp' if isinstance(handle, pyuv.TCP) \
                        else 'udp' if isinstance(handle, pyuv.UDP) \
                        else 'pipe'
            self.send(htype)

    def send(self, command, handle=None):
        line = '{}\n'.format(command).encode('ascii')
        if handle is not None:
            self._transport.write(line, handle)
        else:
            self._transport.write(line)

    @switchpoint
    def call(self, command, handle=None):
        self.send(command, handle)
        value = self._queue.get()
        return value


class IpcServer(Server):

    def __init__(self, server_context=None):
        def protocol_factory():
            return IpcProtocol(self, server_context)
        super(IpcServer, self).__init__(protocol_factory)


class IpcClient(Client):

    def __init__(self):
        super(IpcClient, self).__init__(IpcProtocol)

    protocol = Client.protocol
    delegate_method(protocol, IpcProtocol.send)
    delegate_method(protocol, IpcProtocol.call)


class TestIpc(UnitTest):

    def test_simple(self):
        server = IpcServer()
        pipe = self.pipename()
        server.listen(pipe)
        client = IpcClient()
        client.connect(pipe)
        self.assertEqual(client.call('ping'), 'pong')
        client.close()
        server.close()

    def test_pass_handle(self):
        server = IpcServer()
        pipe = self.pipename()
        server.listen(pipe, ipc=True)
        client = IpcClient()
        client.connect(pipe, ipc=True)
        self.assertEqual(client.call('type'), 'pipe')
        s1, s2 = socketpair()
        h2 = pyuv.Pipe(get_hub().loop)
        h2.open(s2.fileno())
        client.call('handle', h2)
        c1 = IpcClient()
        c1.connect(s1.fileno())
        self.assertEqual(c1.call('ping'), 'pong')
        self.assertEqual(c1.call('type'), 'tcp')
        s1.close(); s2.close()
        c1.close(); h2.close()
        client.close(); server.close()

    def test_pass_handle_over_ssl(self):
        server = IpcServer()
        pipe = self.pipename()
        server.listen(pipe, ipc=True, **self.ssl_s_args)
        client = IpcClient()
        client.connect(pipe, ipc=True, **self.ssl_cp_args)
        self.assertEqual(client.call('type'), 'pipe')
        s1, s2 = socketpair()
        h2 = pyuv.Pipe(get_hub().loop)
        h2.open(s2.fileno())
        client.call('handle', h2)
        c1 = IpcClient()
        c1.connect(s1.fileno())
        self.assertEqual(c1.call('ping'), 'pong')
        self.assertEqual(c1.call('type'), 'tcp')
        s1.close(); s2.close()
        c1.close(); h2.close()
        client.close(); server.close()

    def test_pass_ssl_handle(self):
        server = IpcServer(self.ssl_s_args['ssl'])
        pipe = self.pipename()
        server.listen(pipe, ipc=True)
        client = IpcClient()
        client.connect(pipe, ipc=True)
        self.assertEqual(client.call('type'), 'pipe')
        s1, s2 = socketpair()
        h2 = pyuv.Pipe(get_hub().loop)
        h2.open(s2.fileno())
        client.call('ssl_handle', h2)
        c1 = IpcClient()
        c1.connect(s1.fileno(), **self.ssl_cp_args)
        self.assertEqual(c1.call('ping'), 'pong')
        self.assertEqual(c1.call('type'), 'tcp')
        s1.close(); s2.close()
        c1.close(); h2.close()
        client.close(); server.close()

    def test_pass_ssl_handle_over_ssl(self):
        server = IpcServer(self.ssl_s_args['ssl'])
        pipe = self.pipename()
        server.listen(pipe, ipc=True, **self.ssl_s_args)
        client = IpcClient()
        client.connect(pipe, ipc=True, **self.ssl_cp_args)
        self.assertEqual(client.call('type'), 'pipe')
        s1, s2 = socketpair()
        h2 = pyuv.Pipe(get_hub().loop)
        h2.open(s2.fileno())
        client.call('ssl_handle', h2)
        c1 = IpcClient()
        c1.connect(s1.fileno(), **self.ssl_cp_args)
        self.assertEqual(c1.call('ping'), 'pong')
        self.assertEqual(c1.call('type'), 'tcp')
        s1.close(); s2.close()
        c1.close(); h2.close()
        client.close(); server.close()


if __name__ == '__main__':
    unittest.main()
