#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import socket
import unittest
import pyuv

from support import UnitTest
from gruvi.transports import TransportError, Transport, DatagramTransport


class ProtocolLogger(object):
    """Utility protocol class that implements both the stream and datagram
    protocols and that logs all callbacks."""

    def __init__(self):
        self.events = []
        self.transport = None

    def get_events(self, typ):
        return [ev for ev in self.events if ev[0] == typ]

    def connection_made(self, transport):
        self.events.append(('connection_made', transport))
        self.transport = transport

    def data_received(self, data):
        # collapse data_received for easier verification
        if self.events[-1][0] == 'data_received':
            self.events[-1] = ('data_received', self.events[-1][1] + data)
        else:
            self.events.append(('data_received', data))

    def eof_received(self):
        self.events.append(('eof_received',))

    def connection_lost(self, exc=None):
        self.events.append(('connection_lost', exc))

    def datagram_received(self, data, addr):
        self.events.append(('datagram_received', data, addr))

    def error_received(self, exc):
        self.events.append(('error_received', exc))

    def resume_writing(self):
        pass

    def pause_writing(self):
        pass


class EchoServer(ProtocolLogger):

    def data_received(self, data):
        super(EchoServer, self).data_received(data)
        self.transport.write(data)


class EventLoopTest(UnitTest):

    def setUp(self):
        super(EventLoopTest, self).setUp()
        self.loop = pyuv.Loop()
        self.errors = []

    def catch_errors(self, callback):
        # Run *callback*. If it raises an exception, store it and stop the
        # loop.
        def run_callback(*args):
            try:
                callback(*args)
            except Exception as e:
                self.errors.append(e)
                self.loop.stop()
        return run_callback

    def run_loop(self, timeout):
        # Run the loop for at most *timeout* seconds. Re-raise any exception
        # that was catch by a "catch_errors" callback.
        timer = pyuv.Timer(self.loop)
        def stop_loop(handle):
            self.loop.stop()
        timer.start(stop_loop, timeout, 0)
        self.loop.run()
        if self.errors:
            raise self.errors[0]


class TransportTest(object):

    def create_handle(self):
        raise NotImplementedError

    def bind_handle(self, handle):
        raise NotImplementedError

    def create_transport(self, handle, protocol, server_side):
        transport = Transport(handle)
        transport.start(protocol)
        return transport

    def test_echo(self):
        # Test a simple echo server. The client writes some data end then
        # writes an EOF (if the transport supports writing EOF). The server
        # echos and upon receipt of EOF will close the connection.
        @self.catch_errors
        def echo_server(handle, error):
            if error:
                raise TransportError.from_errno(error)
            client = self.create_handle()
            handle.accept(client)
            protocols[0] = EchoServer()
            transports[0] = self.create_transport(client, protocols[0], True)
        @self.catch_errors
        def echo_client(handle, error):
            if error:
                raise TransportError.from_errno(error)
            protocols[1] = ProtocolLogger()
            trans = transports[1] = self.create_transport(handle, protocols[1], False)
            trans.write(b'foo\n')
            trans.write(b'bar\n')
            trans.writelines([b'qux', b'quux'])
            if trans.can_write_eof():
                trans.write_eof()
        transports = [None, None]
        protocols = [None, None]
        server = self.create_handle()
        addr = self.bind_handle(server)
        server.listen(echo_server)
        client = self.create_handle()
        client.connect(addr, echo_client)
        self.run_loop(0.1)
        strans, ctrans = transports
        sproto, cproto = protocols
        self.assertIsInstance(strans, Transport)
        self.assertIsInstance(ctrans, Transport)
        self.assertIsInstance(sproto, EchoServer)
        self.assertIsInstance(cproto, ProtocolLogger)
        ctrans.close()
        self.run_loop(0.1)
        sevents = sproto.events
        self.assertIn(len(sevents), (3, 4))
        self.assertEqual(sevents[0], ('connection_made', strans))
        self.assertEqual(sevents[1], ('data_received', b'foo\nbar\nquxquux'))
        if strans.can_write_eof():
            self.assertEqual(sevents[2], ('eof_received',))
        self.assertEqual(sevents[-1][0], 'connection_lost')
        cevents = cproto.events
        self.assertIn(len(cevents), (3, 4))
        self.assertEqual(cevents[0], ('connection_made', ctrans))
        self.assertEqual(cevents[1], ('data_received', b'foo\nbar\nquxquux'))
        if ctrans.can_write_eof():
            self.assertEqual(cevents[2], ('eof_received',))
        self.assertEqual(cevents[-1][0], 'connection_lost')


class TestTcpTransport(TransportTest, EventLoopTest):

    def create_handle(self):
        return pyuv.TCP(self.loop)

    def bind_handle(self, handle):
        host = socket.gethostbyname('localhost')
        handle.bind((host, 0))
        return handle.getsockname()


class TestPipeTransport(TransportTest, EventLoopTest):

    def create_handle(self):
        return pyuv.Pipe(self.loop)

    def bind_handle(self, handle):
        addr = self.pipename('test-pipe')
        handle.bind(addr)
        return addr


class TestUdpTransport(EventLoopTest):

    def create_handle(self):
        return pyuv.UDP(self.loop)

    def bind_handle(self, handle):
        host = socket.gethostbyname('localhost')
        handle.bind((host, 0))
        return handle.getsockname()

    def create_transport(self, handle, protocol):
        transport = DatagramTransport(handle)
        transport.start(protocol)
        return transport

    def test_echo(self):
        server = self.create_handle()
        saddr = self.bind_handle(server)
        sproto = ProtocolLogger()
        strans = self.create_transport(server, sproto)
        client = self.create_handle()
        caddr = self.bind_handle(client)
        cproto = ProtocolLogger()
        ctrans = self.create_transport(client, cproto)
        # Try 5 times (since UDP is lossy)
        for i in range(5):
            ctrans.sendto(b'foo', saddr)
        for i in range(5):
            strans.sendto(b'bar', caddr)
        self.run_loop(0.1)
        sevents = sproto.get_events('datagram_received')
        self.assertGreater(len(sevents), 0)
        for event in sevents:
            self.assertEqual(event[1], b'foo')
            self.assertEqual(event[2], caddr)
        cevents = cproto.get_events('datagram_received')
        self.assertGreater(len(cevents), 0)
        for event in cevents:
            self.assertEqual(event[1], b'bar')
            self.assertEqual(event[2], saddr)


if __name__ == '__main__':
    unittest.main()
