#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import time
import functools

import gruvi
from gruvi import dbus_ffi, txdbus, compat
from gruvi.protocols import errno
from gruvi.dbus import DBusParser, DBusBase, DBusClient

from support import *


_keepalive = None

def set_buffer(ctx, buf):
    # See note in DBusParser
    global _keepalive
    _keepalive = ctx.buf = dbus_ffi.ffi.new('char[]', buf)
    ctx.buflen = len(buf)
    ctx.offset = 0

def split_string(s):
    ctx = dbus_ffi.ffi.new('struct context *')
    set_buffer(ctx, s)
    dbus_ffi.lib.split(ctx)
    return ctx


class TestDBusFFI(UnitTest):

    def test_simple(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        ctx = split_string(m)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m))
        self.assertEqual(ctx.big_endian, 0)
        self.assertEqual(ctx.serial, 1)

    def test_big_endian(self):
        m = b'B\1\0\1\0\0\0\0\0\0\0\1\0\0\0\0'
        ctx = split_string(m)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m))
        self.assertEqual(ctx.big_endian, 1)
        self.assertEqual(ctx.serial, 1)

    def test_invalid_endian(self):
        m = b'X\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.ERROR_ENDIAN)
        self.assertEqual(ctx.offset, 0)

    def test_message_type(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        for i in range(1, 4):
            m = m[:1] + chr(i).encode('ascii') + m[2:]
            ctx = split_string(m)
            self.assertEqual(ctx.error, 0)
            self.assertEqual(ctx.offset, len(m))

    def test_invalid_message_type(self):
        m = b'l\0\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.ERROR_TYPE)
        self.assertEqual(ctx.offset, 1)
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.ERROR_TYPE)
        self.assertEqual(ctx.offset, 1)

    def test_flags(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        for i in range(1, 4):
            m = m[:2] + chr(i).encode('ascii') + m[3:]
            ctx = split_string(m)
            self.assertEqual(ctx.error, 0)
            self.assertEqual(ctx.offset, len(m))

    def test_invalid_flags(self):
        m = b'l\1\4\1\0\0\0\0\1\0\0\0\0\0\0\0'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.ERROR_FLAGS)
        self.assertEqual(ctx.offset, 2)

    def test_invalid_version(self):
        m = b'l\1\0\2\0\0\0\0\1\0\0\0\0\0\0\0'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.ERROR_VERSION)
        self.assertEqual(ctx.offset, 3)

    def test_invalid_serial(self):
        m = b'l\1\0\1\0\0\0\0\0\0\0\0\0\0\0\0'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.ERROR_SERIAL)
        self.assertEqual(ctx.offset, 11)

    def test_header_array(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\4\0\0\0h234'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.INCOMPLETE)
        self.assertEqual(ctx.offset, len(m))
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\4\0\0\0h2345678'
        ctx = split_string(m)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m))
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\10\0\0\0h2345678'
        ctx = split_string(m)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m))
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\11\0\0\0h23456781234567'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.INCOMPLETE)
        self.assertEqual(ctx.offset, len(m))
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\11\0\0\0h234567812345678'
        ctx = split_string(m)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m))

    def test_body_size(self):
        m = b'l\1\0\1\4\0\0\0\1\0\0\0\0\0\0\0b23'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.INCOMPLETE)
        self.assertEqual(ctx.offset, len(m))
        m = b'l\1\0\1\4\0\0\0\1\0\0\0\0\0\0\0b234'
        ctx = split_string(m)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m))
        m = b'l\1\0\1\xf0\xff\xff\x0f\1\0\0\0\0\0\0\0b234'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.INCOMPLETE)
        self.assertEqual(ctx.offset, len(m))

    def test_invalid_body_size(self):
        m = b'l\1\0\1\xf1\xff\xff\x0f\1\0\0\0\0\0\0\0b234'
        ctx = split_string(m)
        self.assertEqual(ctx.error, dbus_ffi.lib.ERROR_TOO_LARGE)
        self.assertEqual(ctx.offset, 7)

    def test_header_and_body(self):
        m = b'l\1\0\1\4\0\0\0\1\0\0\0\4\0\0\0h23456781234'
        ctx = split_string(m)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m))

    def test_multiple(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0' + \
            b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        ctx = split_string(m)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m)/2)
        error = dbus_ffi.lib.split(ctx)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(m))
 
    def test_incremental(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        offset = state = 0
        ctx = dbus_ffi.ffi.new('struct context *')
        for i in range(len(m)-1):
            set_buffer(ctx, m[i:i+1])
            error = dbus_ffi.lib.split(ctx)
            self.assertEqual(error, dbus_ffi.lib.INCOMPLETE)
            self.assertEqual(error, ctx.error)
            self.assertEqual(ctx.offset, 1)
        set_buffer(ctx, m[-1:])
        error = dbus_ffi.lib.split(ctx)
        self.assertEqual(error, 0)
        self.assertEqual(ctx.error, error)
        self.assertEqual(ctx.offset, 1)

    def test_incremental_with_body(self):
        m = b'l\1\0\1\4\0\0\0\1\0\0\0\0\0\0\0abcd'
        ctx = dbus_ffi.ffi.new('struct context *')
        for i in range(len(m)-1):
            set_buffer(ctx, m[i:i+1])
            error = dbus_ffi.lib.split(ctx)
            self.assertEqual(error, dbus_ffi.lib.INCOMPLETE)
            self.assertEqual(ctx.error, error)
            self.assertEqual(ctx.offset, 1)
        set_buffer(ctx, m[-1:])
        error = dbus_ffi.lib.split(ctx)
        self.assertEqual(error, 0)
        self.assertEqual(ctx.error, error)
        self.assertEqual(ctx.offset, 1)

    def test_incremental_with_header(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\10\0\0\0h2345678'
        ctx = dbus_ffi.ffi.new('struct context *')
        for i in range(len(m)-1):
            set_buffer(ctx, m[i:i+1])
            error = dbus_ffi.lib.split(ctx)
            self.assertEqual(error, dbus_ffi.lib.INCOMPLETE)
            self.assertEqual(ctx.error, error)
            self.assertEqual(ctx.offset, 1)
        set_buffer(ctx, m[-1:])
        error = dbus_ffi.lib.split(ctx)
        self.assertEqual(error, 0)
        self.assertEqual(ctx.error, error)
        self.assertEqual(ctx.offset, 1)

    def test_incremental_with_header_and_body(self):
        m = b'l\1\0\1\4\0\0\0\1\0\0\0\4\0\0\0h23456781234'
        ctx = dbus_ffi.ffi.new('struct context *')
        for i in range(len(m)-1):
            set_buffer(ctx, m[i:i+1])
            error = dbus_ffi.lib.split(ctx)
            self.assertEqual(error, dbus_ffi.lib.INCOMPLETE)
            self.assertEqual(ctx.error, error)
            self.assertEqual(ctx.offset, 1)
        set_buffer(ctx, m[-1:])
        error = dbus_ffi.lib.split(ctx)
        self.assertEqual(error, 0)
        self.assertEqual(ctx.error, error)
        self.assertEqual(ctx.offset, 1)

    def test_performance(self):
        m = b'l\1\0\1\x64\0\0\0\1\0\0\0\0\0\0\0' + (b'x'*100)
        buf = m * 100
        ctx = dbus_ffi.ffi.new('struct context *')
        nbytes = 0
        t1 = time.time()
        while True:
            t2 = time.time()
            if t2 - t1 > 0.2:
                break
            set_buffer(ctx, buf)
            while ctx.offset != len(buf):
                error = dbus_ffi.lib.split(ctx)
                self.assertEqual(error, 0)
                self.assertEqual(ctx.error, error)
                self.assertEqual(ctx.offset % len(m), 0)
            nbytes += len(buf)
        speed = nbytes / (1024 * 1024 * (t2 - t1))
        print('Throughput: {0:.2f} MiB/sec'.format(speed))


class TestDBusParser(UnitTest):

    def test_simple(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        parser = DBusParser()
        parser.feed(m)
        msg = parser.pop_message()
        self.assertIsInstance(msg, txdbus.DBusMessage)
        self.assertEqual(msg._messageType, 1)
        self.assertEqual(msg.expectReply, True)
        self.assertEqual(msg.autoStart, True)
        self.assertEqual(msg.endian, ord(b'l'))
        self.assertEqual(msg.bodyLength, 0)
        msg = parser.pop_message()
        self.assertIsNone(msg)

    def test_multiple(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0' \
            b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        parser = DBusParser()
        parser.feed(m)
        msg = parser.pop_message()
        self.assertIsInstance(msg, txdbus.DBusMessage)
        self.assertEqual(msg._messageType, 1)
        msg = parser.pop_message()
        self.assertIsInstance(msg, txdbus.DBusMessage)
        self.assertEqual(msg._messageType, 1)
        msg = parser.pop_message()
        self.assertIsNone(msg)

    def test_incremental(self):
        m = b'l\1\0\1\0\0\0\0\1\0\0\0\0\0\0\0'
        parser = DBusParser()
        for i in range(len(m)-1):
            parser.feed(m[i:i+1])
            self.assertIsNone(parser.pop_message())
        parser.feed(m[-1:])
        msg = parser.pop_message()
        self.assertIsInstance(msg, txdbus.DBusMessage)

    def test_illegal_message(self):
        m = b'l\1\0\2\0\0\0\0\1\0\0\0\0\0\0\0'
        parser = DBusParser()
        nbytes = parser.feed(m)
        self.assertNotEqual(nbytes, len(m))
        self.assertEqual(parser.error, errno.FRAMING_ERROR)

    def test_maximum_message_size_exceeded(self):
        parser = DBusParser()
        parser.max_message_size = 100
        m = b'l\1\0\1\0\1\0\0\1\0\0\0\0\0\0\0' + b'x' * 256
        nbytes = parser.feed(m)
        self.assertNotEqual(nbytes, len(m))
        self.assertEqual(parser.error, errno.MESSAGE_TOO_LARGE)


def uses_host_dbus(test):
    @functools.wraps(test)
    def maybe_run(*args, **kwargs):
        addr = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
        if not addr:
            raise SkipTest('this test requires a local D-BUS instance')
        return test(*args, **kwargs)
    return maybe_run


class DummyAuthenticator(object):

    s_start, s_begin, s_authenticated = range(3)

    def __init__(self):
        self._state = self.s_start
        self._username = None

    @property
    def username(self):
        return self._username

    def feed(self, line):
        if self._state == self.s_start:
            if line == b'\0AUTH EXTERNAL\r\n':
                self._state = self.s_begin
                return b'OK\r\n'
        elif self._state == self.s_begin:
            if line == b'BEGIN\r\n':
                self._state = self.s_authenticated
                self._username = '<external>'


def echo_app(message, endpoint, transport):
    if not isinstance(message, txdbus.MethodCallMessage):
        return
    method = message.member
    if method == 'Hello':
        signature = 's'
        body = ':1'
    elif method == 'Echo':
        signature = message.signature
        body = message.body
    response = txdbus.MethodReturnMessage(message.serial,
                        signature=signature, body=body)
    return response


class TestDBus(UnitTest):

    @uses_host_dbus
    def test_host(self):
        client = gruvi.dbus.DBusClient()
        client.connect('system')
        result = client.call_method('org.freedesktop.DBus',
                                    '/org/freedesktop/DBus',
                                    'org.freedesktop.DBus', 'ListNames')
        self.assertIsInstance(result, list)
        for name in result:
            self.assertIsInstance(name, compat.text_type)

    def test_simple(self):
        server = DBusBase(echo_app)
        server._authenticator = DummyAuthenticator
        server._listen(('localhost', 0))
        addr = server.transport.getsockname()
        client = DBusClient()
        addr = 'tcp:host={0},port={1}'.format(*addr)
        client.connect(addr)
        result = client.call_method('service.com', '/path', 'iface.com', 'Echo',
                                    signature='ss', args=('foo', 'bar'))
        self.assertEqual(result, ['foo', 'bar'])


if __name__ == '__main__':
    unittest.main(buffer=True)
