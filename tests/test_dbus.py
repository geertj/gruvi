#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import six
import socket
import unittest
from unittest import SkipTest

import gruvi
from gruvi.vendor import txdbus
from gruvi.dbus import DbusError, DbusMethodCallError
from gruvi.dbus import DbusProtocol, DbusClient, DbusServer
from gruvi.dbus import parse_dbus_header, TxdbusAuthenticator
from gruvi.transports import TransportError

from support import UnitTest, MockTransport


class TestParseDbusHeader(UnitTest):

    def test_simple(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        self.assertEqual(parse_dbus_header(m), len(m))

    def test_big_endian(self):
        m = b'B\1\0\1\0\0\0\0\0\0\0\1\0\0\0\0'
        self.assertEqual(parse_dbus_header(m), len(m))

    def test_header_array(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\10\0\0\0h2345678'
        self.assertEqual(parse_dbus_header(m), len(m))
        for l in range(16, len(m)):
            self.assertEqual(parse_dbus_header(m[:l]), len(m))

    def test_padding(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\11\0\0\0h234567812345678'
        self.assertEqual(parse_dbus_header(m), len(m))
        for l in range(16, len(m)):
            self.assertEqual(parse_dbus_header(m[:l]), len(m))

    def test_body_size(self):
        m = b'l\1\0\1\4\0\0\0\1\0\0\0\0\0\0\0b234'
        self.assertEqual(parse_dbus_header(m), len(m))
        for l in range(16, len(m)):
            self.assertEqual(parse_dbus_header(m[:l]), len(m))

    def test_illegal_endian(self):
        m = b'L\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        self.assertRaises(ValueError, parse_dbus_header, m)
        m = b'b\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        self.assertRaises(ValueError, parse_dbus_header, m)

    def test_illegal_type(self):
        m = b'l\0\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        self.assertRaises(ValueError, parse_dbus_header, m)
        m = b'l\5\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        self.assertRaises(ValueError, parse_dbus_header, m)

    def test_illegal_serial(self):
        m = b'l\1\0\1\0\0\0\0\0\0\0\0\0\0\0\0'
        self.assertRaises(ValueError, parse_dbus_header, m)


class TestDbusProtocol(UnitTest):

    def setUp(self):
        super(TestDbusProtocol, self).setUp()
        self.messages = []
        self.protocols = []

    def store_messages(self, message, transport, protocol):
        self.messages.append(message)
        self.protocols.append(protocol)

    def store_and_echo_messages(self, message, transport, protocol):
        self.messages.append(message)
        self.protocols.append(protocol)
        response = txdbus.SignalMessage(message.path, message.member, message.interface,
                                        signature=message.signature, body=message.body)
        protocol.send_message(response)

    def test_auth_missing_creds_byte(self):
        # The first thing a client should send to the server is a '\0' byte. If
        # not, the server should close the connection.
        transport = MockTransport()
        protocol = DbusProtocol(server_side=True)
        transport.start(protocol)
        self.assertFalse(transport._closed.is_set())
        protocol.data_received(b'\1')
        self.assertIsInstance(protocol._error, DbusError)
        self.assertTrue(transport._closed.is_set())

    def test_auth_non_ascii(self):
        # After the '\0' byte, an authentiction phase happens. The
        # authentication protocol is line based and all lines should be ascii.
        transport = MockTransport()
        protocol = DbusProtocol(server_side=True)
        transport.start(protocol)
        self.assertFalse(transport._closed.is_set())
        protocol.data_received(b'\0\xff\r\n')
        self.assertIsInstance(protocol._error, DbusError)
        self.assertTrue(transport._closed.is_set())

    def test_auth_long_line(self):
        # An authentication line should not exceed the maximum line size.
        transport = MockTransport()
        protocol = DbusProtocol(server_side=True, server_guid='foo')
        protocol.max_line_size = 5
        transport.start(protocol)
        self.assertFalse(transport._closed.is_set())
        protocol.data_received(b'\0AUTH ANONYMOUS\r\n')
        self.assertIsInstance(protocol._error, DbusError)
        self.assertTrue(transport._closed.is_set())

    def test_auth_ok(self):
        # Test anonymous authenication. Ensure that the server GUID is
        # correctly sent back.
        transport = MockTransport()
        protocol = DbusProtocol(server_side=True, server_guid='foo')
        transport.start(protocol)
        protocol.data_received(b'\0AUTH ANONYMOUS\r\nBEGIN\r\n')
        buf = transport.buffer.getvalue()
        self.assertTrue(buf.startswith(b'OK foo'))
        auth = protocol._authenticator
        self.assertTrue(auth.authenticationSucceeded())
        self.assertTrue(auth.getGUID(), 'foo')
        self.assertFalse(transport._closed.is_set())

    def test_missing_hello(self):
        # After authentication, the first message should be a "Hello".
        # Otherwise, the server should close the connection.
        transport = MockTransport()
        protocol = DbusProtocol(self.store_messages, server_side=True, server_guid='foo')
        transport.start(protocol)
        protocol.data_received(b'\0AUTH ANONYMOUS\r\nBEGIN\r\n')
        message = txdbus.MethodCallMessage('/my/path', 'Method')
        auth = protocol._authenticator
        self.assertTrue(auth.authenticationSucceeded())
        protocol.data_received(message.rawMessage)
        self.assertIsInstance(protocol._error, DbusError)
        self.assertTrue(transport._closed.is_set())

    def test_send_message(self):
        # After the "Hello" message, it should be possible to send other
        # messages.
        transport = MockTransport()
        protocol = DbusProtocol(self.store_messages, server_side=True, server_guid='foo')
        transport.start(protocol)
        protocol.data_received(b'\0AUTH ANONYMOUS\r\nBEGIN\r\n')
        auth = protocol._authenticator
        self.assertTrue(auth.authenticationSucceeded())
        message = txdbus.MethodCallMessage('/org/freedesktop/DBus', 'Hello',
                        interface='org.freedesktop.DBus', destination='org.freedesktop.DBus')
        protocol.data_received(message.rawMessage)
        gruvi.sleep(0)
        self.assertIsNone(protocol._error)
        self.assertFalse(transport._closed.is_set())
        self.assertTrue(protocol._name_acquired)
        self.assertEqual(len(self.messages), 0)
        message = txdbus.MethodCallMessage('/my/path', 'Method')
        protocol.data_received(message.rawMessage)
        gruvi.sleep(0)
        self.assertIsNone(protocol._error)
        self.assertFalse(transport._closed.is_set())
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.messages[0].path, '/my/path')
        self.assertEqual(self.messages[0].member, 'Method')
        self.assertEqual(self.protocols, [protocol])

    def test_send_message_incremental(self):
        # Send a message byte by byte. The protocol should be able process it.
        transport = MockTransport()
        protocol = DbusProtocol(self.store_messages, server_side=True, server_guid='foo')
        transport.start(protocol)
        authexchange = b'\0AUTH ANONYMOUS\r\nBEGIN\r\n'
        for i in range(len(authexchange)):
            protocol.data_received(authexchange[i:i+1])
        auth = protocol._authenticator
        self.assertTrue(auth.authenticationSucceeded())
        message = txdbus.MethodCallMessage('/org/freedesktop/DBus', 'Hello',
                        interface='org.freedesktop.DBus', destination='org.freedesktop.DBus')
        for i in range(len(message.rawMessage)):
            protocol.data_received(message.rawMessage[i:i+1])
        gruvi.sleep(0)
        self.assertIsNone(protocol._error)
        self.assertFalse(transport._closed.is_set())
        self.assertEqual(len(self.messages), 0)
        message = txdbus.MethodCallMessage('/my/path', 'Method')
        for i in range(len(message.rawMessage)):
            protocol.data_received(message.rawMessage[i:i+1])
        gruvi.sleep(0)
        self.assertIsNone(protocol._error)
        self.assertFalse(transport._closed.is_set())
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.messages[0].path, '/my/path')
        self.assertEqual(self.messages[0].member, 'Method')
        self.assertEqual(self.protocols, [protocol])

    def test_send_message_too_large(self):
        # Send a message that exceeds the maximum message size. The connection
        # should be closed.
        transport = MockTransport()
        protocol = DbusProtocol(self.store_messages, server_side=True, server_guid='foo')
        transport.start(protocol)
        protocol.data_received(b'\0AUTH ANONYMOUS\r\nBEGIN\r\n')
        message = txdbus.MethodCallMessage('/org/freedesktop/DBus', 'Hello',
                        interface='org.freedesktop.DBus', destination='org.freedesktop.DBus')
        protocol.data_received(message.rawMessage)
        gruvi.sleep(0)
        self.assertTrue(protocol._name_acquired)
        # Send a signal with a size equal to the high-water mark. This should work.
        message = txdbus.SignalMessage('/my/path', 'Signal', 'my.iface',
                                       signature='s', body=['x'*100])
        msglen = len(message.rawMessage)
        self.assertGreater(msglen, 100)
        protocol.max_message_size = msglen
        protocol.data_received(message.rawMessage)
        gruvi.sleep(0)
        self.assertIsNone(protocol._error)
        self.assertFalse(transport._closed.is_set())
        self.assertEqual(len(self.messages), 1)
        # Now send a signal with a size larger than the high-water mark. This should fail.
        message = txdbus.SignalMessage('/my/path', 'Signal', 'my.iface',
                                       signature='s', body=['x'*100])
        msglen = len(message.rawMessage)
        protocol.max_message_size = msglen-1
        protocol.data_received(message.rawMessage)
        gruvi.sleep(0)
        self.assertIsInstance(protocol._error, DbusError)
        self.assertTrue(transport._closed.is_set())
        self.assertEqual(len(self.messages), 1)

    def test_read_write_flow_control(self):
        # Send a lot of messages filling up the protocol read buffer.
        transport = MockTransport()
        protocol = DbusProtocol(self.store_and_echo_messages, server_side=True)
        transport.start(protocol)
        protocol.data_received(b'\0AUTH ANONYMOUS\r\nBEGIN\r\n')
        auth = protocol._authenticator
        self.assertTrue(auth.authenticationSucceeded())
        message = txdbus.MethodCallMessage('/org/freedesktop/DBus', 'Hello',
                        interface='org.freedesktop.DBus', destination='org.freedesktop.DBus')
        protocol.data_received(message.rawMessage)
        gruvi.sleep(0)
        self.assertTrue(protocol._name_acquired.is_set())
        interrupted = 0
        message = txdbus.SignalMessage('/my/path', 'Signal', 'my.iface',
                                       signature='s', body=['x'*100])
        msglen = len(message.rawMessage)
        protocol.max_queue_size = 10
        transport.drain()
        transport.set_write_buffer_limits(7*msglen)
        for i in range(100):
            # Fill up protocol message queue
            protocol.data_received(message.rawMessage)
            if transport._reading:
                continue
            interrupted += 1
            self.assertEqual(protocol._queue.qsize(), 10)
            # Run the dispatcher to fill up the transport write buffer
            gruvi.sleep(0)
            # Now the write buffer is full and the read buffer still contains
            # some entries because it is larger.
            self.assertGreater(protocol._queue.qsize(), 0)
            self.assertFalse(transport._can_write.is_set())
            transport.drain()
        # Should be interrupted > 10 times. The write buffer is the limiting factor
        # not the read buffer.
        self.assertGreater(interrupted, 10)


def echo_app(message, transport, protocol):
    # Test application that echos D-Bus arguments
    if not isinstance(message, txdbus.MethodCallMessage):
        return
    if message.member == 'Echo':
        reply = txdbus.MethodReturnMessage(message.serial, signature=message.signature,
                                           body=message.body)
    elif message.member == 'Error':
        reply = txdbus.ErrorMessage('Echo.Error', message.serial, signature=message.signature,
                                    body=message.body)
    else:
        return
    protocol.send_message(reply)


class TestGruviDbus(UnitTest):

    def setUp(self):
        super(TestGruviDbus, self).setUp()
        TxdbusAuthenticator.cookie_dir = self.tempdir

    def test_auth_pipe(self):
        # Test that authentication works over a Pipe.
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        cproto = client.protocol
        cauth = cproto._authenticator
        sproto = list(server.connections)[0][1]
        sauth = sproto._authenticator
        self.assertTrue(cauth.authenticationSucceeded())
        self.assertTrue(sauth.authenticationSucceeded())
        self.assertIsInstance(cproto.server_guid, six.text_type)
        self.assertTrue(cproto.server_guid.isalnum())
        self.assertEqual(cproto.server_guid, cauth.getGUID())
        self.assertEqual(cproto.server_guid, sproto.server_guid)
        self.assertEqual(sproto.server_guid, sauth.getGUID())
        self.assertEqual(cauth.getMechanismName(), sauth.getMechanismName())
        if hasattr(socket, 'SO_PEERCRED'):
            self.assertEqual(cauth.getMechanismName(), 'EXTERNAL')
        elif hasattr(os, 'fork'):
            self.assertEqual(cauth.getMechanismName(), 'DBUS_COOKIE_SHA1')
        else:
            self.assertEqual(cauth.getMechanismName(), 'ANONYMOUS')
        client.close()
        server.close()

    def test_auth_tcp(self):
        # Test that authentication works over TCP
        server = DbusServer(echo_app)
        addr = 'tcp:host=127.0.0.1,port=0'
        server.listen(addr)
        client = DbusClient()
        client.connect(server.addresses[0])
        cproto = client.protocol
        cauth = cproto._authenticator
        sproto = list(server.connections)[0][1]
        sauth = sproto._authenticator
        self.assertTrue(cauth.authenticationSucceeded())
        self.assertTrue(sauth.authenticationSucceeded())
        self.assertIsInstance(cproto.server_guid, six.text_type)
        self.assertTrue(cproto.server_guid.isalnum())
        self.assertEqual(cproto.server_guid, cauth.getGUID())
        self.assertEqual(cproto.server_guid, sproto.server_guid)
        self.assertEqual(sproto.server_guid, sauth.getGUID())
        self.assertEqual(cauth.getMechanismName(), sauth.getMechanismName())
        if hasattr(os, 'fork'):
            self.assertEqual(cauth.getMechanismName(), 'DBUS_COOKIE_SHA1')
        else:
            self.assertEqual(cauth.getMechanismName(), 'ANONYMOUS')
        client.close()
        server.close()

    def test_get_unique_name(self):
        # Ensure that get_unique_name() works client and server side
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        unique_name = client.get_unique_name()
        self.assertIsInstance(unique_name, six.text_type)
        self.assertTrue(unique_name.startswith(':'))
        sproto = list(server.connections)[0][1]
        self.assertEqual(unique_name, sproto.get_unique_name())
        server.close()
        client.close()

    def test_call_method(self):
        # Ensure that calling a method over a Unix socket works.
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        result = client.call_method('bus.name', '/path', 'my.iface', 'Echo')
        self.assertEqual(result, ())
        server.close()
        client.close()

    def test_call_method_tcp(self):
        # Ensure that calling a method over TCP works.
        server = DbusServer(echo_app)
        addr = 'tcp:host=127.0.0.1,port=0'
        server.listen(addr)
        client = DbusClient()
        client.connect(server.addresses[0])
        result = client.call_method('bus.name', '/path', 'my.iface', 'Echo')
        self.assertEqual(result, ())
        server.close()
        client.close()

    def test_call_method_str_args(self):
        # Ensure that calling a method with string arguments works.
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        result = client.call_method('bus.name', '/path', 'my.iface', 'Echo',
                                    signature='s', args=['foo'])
        self.assertEqual(result, ('foo',))
        result = client.call_method('bus.name', '/path', 'my.iface', 'Echo',
                                    signature='ss', args=['foo', 'bar'])
        self.assertEqual(result, ('foo', 'bar'))
        server.close()
        client.close()

    def test_call_method_int_args(self):
        # Ensure that calling a method with integer arguments works.
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        result = client.call_method('bus.name', '/path', 'my.iface', 'Echo',
                                    signature='i', args=[1])
        self.assertEqual(result, (1,))
        result = client.call_method('bus.name', '/path', 'my.iface', 'Echo',
                                    signature='ii', args=[1, 2])
        self.assertEqual(result, (1, 2))
        server.close()
        client.close()

    def test_call_method_error(self):
        # Ensure that a method can return an error and that in this case a
        # DbusMethodCallError is raised.
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        exc = self.assertRaises(DbusMethodCallError, client.call_method,
                               'bus.name', '/path', 'my.iface', 'Error')
        self.assertEqual(exc.error, 'Echo.Error')
        self.assertEqual(exc.args, ())
        server.close()
        client.close()

    def test_call_method_error_args(self):
        # Call a method that will return an error with arguments. The arguments
        # should be available from the exception.
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        exc = self.assertRaises(DbusMethodCallError, client.call_method,
                               'bus.name', '/path', 'my.iface', 'Error',
                               signature='ss', args=('foo', 'bar'))
        self.assertEqual(exc.error, 'Echo.Error')
        self.assertEqual(exc.args, ('foo', 'bar'))
        server.close()
        client.close()

    def test_send_garbage(self):
        # Send random garbage and ensure the connection gets dropped.
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        exc = None
        try:
            while True:
                chunk = os.urandom(100)
                client.transport.write(chunk)
                gruvi.sleep(0)
        except Exception as e:
            exc = e
        self.assertIsInstance(exc, TransportError)
        server.close()
        client.close()

    def test_connection_limit(self):
        # Establish more connections than the DBUS server is willing to accept.
        # The connections should be closed.
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        server.max_connections = 2
        clients = []
        exc = None
        try:
            for i in range(4):
                client = DbusClient()
                client.connect(addr)
                clients.append(client)
        except Exception as e:
            exc = e
        self.assertIsInstance(exc, TransportError)
        self.assertEqual(len(server.connections), server.max_connections)
        for client in clients:
            client.close()
        server.close()


class TestNativeDbus(UnitTest):

    def setUp(self):
        if not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
            raise SkipTest('D-BUS session bus not available')
        super(TestNativeDbus, self).setUp()

    def test_get_unique_name(self):
        # Ensure that get_unique_name() works
        client = DbusClient()
        client.connect('session')
        unique_name = client.get_unique_name()
        self.assertIsInstance(unique_name, six.text_type)
        self.assertTrue(unique_name.startswith(':'))
        client.close()

    def test_call_listnames(self):
        # Call the ListNames() bus method and ensure the results are a list of
        # strings.
        client = DbusClient()
        client.connect('session')
        result = client.call_method('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                    'org.freedesktop.DBus', 'ListNames')
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 1)
        names = result[0]
        self.assertIsInstance(names, list)
        self.assertGreater(len(names), 0)
        for name in names:
            self.assertIsInstance(name, six.text_type)
        client.close()


if __name__ == '__main__':
    os.environ.setdefault('VERBOSE', '1')
    unittest.main()
