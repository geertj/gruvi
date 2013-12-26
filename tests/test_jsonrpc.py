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
import pyuv

import gruvi
from gruvi import jsonrpc_ffi
from gruvi.jsonrpc import *
from gruvi.jsonrpc import create_response, create_error, JsonRpcParser
from gruvi.protocols import errno
from gruvi.stream import StreamClient
from support import *


_keepalive = None

def set_buffer(ctx, buf):
    global _keepalive  # See note in JsonRpcParser
    _keepalive = ctx.buf = jsonrpc_ffi.ffi.new('char[]', buf)
    ctx.buflen = len(buf)
    ctx.offset = 0

def split_string(s):
    ctx = jsonrpc_ffi.ffi.new('struct context *')
    set_buffer(ctx, s)
    jsonrpc_ffi.lib.split(ctx)
    return ctx


class TestJsonRpcFFI(UnitTest):

    def test_simple(self):
        r = b'{ "foo": "bar" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(r))

    def test_leading_whitespace(self):
        r = b' { "foo": "bar" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(r))
        r = b' \t\n{ "foo": "bar" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(r))

    def test_trailing_whitespace(self):
        r = b'{ "foo": "bar" } '
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(r)-1)
        error = jsonrpc_ffi.lib.split(ctx)
        self.assertEqual(error, ctx.error) == jsonrpc_ffi.lib.INCOMPLETE
        self.assertEqual(ctx.offset, len(r))

    def test_brace_in_string(self):
        r = b'{ "foo": "b{r" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(r))
        r = b'{ "foo": "b}r" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(r))

    def test_string_escape(self):
        r = b'{ "foo": "b\\"}" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, len(r))

    def test_error(self):
        r = b' x { "foo": "bar" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, jsonrpc_ffi.lib.ERROR)
        self.assertEqual(ctx.offset, 1)
        r = b'[ { "foo": "bar" } ]'
        ctx = split_string(r)
        self.assertEqual(ctx.error, jsonrpc_ffi.lib.ERROR)
        self.assertEqual(ctx.offset, 0)

    def test_multiple(self):
        r = b'{ "foo": "bar" } { "baz": "qux" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, 16)
        error = jsonrpc_ffi.lib.split(ctx)
        self.assertEqual(error, ctx.error) == 0
        self.assertEqual(ctx.offset, len(r))

    def test_incremental(self):
        r = b'{ "foo": "bar" }'
        state = 0
        ctx = jsonrpc_ffi.ffi.new('struct context *')
        for i in range(len(r)-1):
            set_buffer(ctx, r[i:i+1])
            error = jsonrpc_ffi.lib.split(ctx)
            self.assertEqual(error, ctx.error) == jsonrpc_ffi.lib.INCOMPLETE
            self.assertEqual(ctx.offset, 1)
        buf = ctx.buf = jsonrpc_ffi.ffi.new('char[]', r[-1:])
        ctx.buflen = 1; ctx.offset = 0
        error = jsonrpc_ffi.lib.split(ctx)
        self.assertEqual(error, ctx.error) == 0
        self.assertEqual(ctx.offset, 1)

    def test_performance(self):
        chunk = b'{' + b'x' * 100 + b'}'
        buf = chunk * 100
        ctx = jsonrpc_ffi.ffi.new('struct context *')
        nbytes = 0
        t1 = time.time()
        while True:
            t2 = time.time()
            if t2 - t1 > 0.5:
                break
            set_buffer(ctx, buf)
            while ctx.offset != len(buf):
                error = jsonrpc_ffi.lib.split(ctx)
                self.assertEqual(error, ctx.error) == 0
            nbytes += len(buf)
        throughput = nbytes / (1024 * 1024 * (t2 - t1))
        print('Throughput: {0:.2f} MiB/sec'.format(throughput))


class TestJsonRpcParser(UnitTest):

    def test_simple(self):
        m = b'{ "id": "1", "method": "foo" }'
        parser = JsonRpcParser()
        parser.feed(m)
        msg = parser.pop_message()
        self.assertIsInstance(msg, dict)
        self.assertEqual(msg, { 'id': '1', 'method': 'foo' })
        msg = parser.pop_message()
        self.assertIsNone(msg)

    def test_multiple(self):
        m = b'{ "id": "1", "method": "foo" }' \
            b'{ "id": "2", "method": "bar" }'
        parser = JsonRpcParser()
        parser.feed(m)
        msg = parser.pop_message()
        self.assertEqual(msg, { 'id': '1', 'method': 'foo' })
        msg = parser.pop_message()
        self.assertEqual(msg, { 'id': '2', 'method': 'bar' })
        msg = parser.pop_message()
        self.assertIsNone(msg)

    def test_whitespace(self):
        m = b'  { "id": "1", "method": "foo" }' \
            b'  { "id": "2", "method": "bar" }'
        parser = JsonRpcParser()
        parser.feed(m)
        msg = parser.pop_message()
        self.assertEqual(msg, { 'id': '1', 'method': 'foo' })
        msg = parser.pop_message()
        self.assertEqual(msg, { 'id': '2', 'method': 'bar' })
        msg = parser.pop_message()
        self.assertIsNone(msg)

    def test_incremental(self):
        m = b'{ "id": "1", "method": "foo" }'
        parser = JsonRpcParser()
        for i in range(len(m)-1):
            parser.feed(m[i:i+1])
            self.assertIsNone(parser.pop_message())
        parser.feed(m[-1:])
        msg = parser.pop_message()
        self.assertEqual(msg, { 'id': '1', 'method': 'foo' })

    def test_framing_error(self):
        m = b'xxx'
        parser = JsonRpcParser()
        nbytes = parser.feed(m)
        self.assertNotEqual(nbytes, len(m))
        self.assertEqual(parser.error, errno.FRAMING_ERROR)

    def test_encoding_error(self):
        m = b'{ xxx\xff }'
        parser = JsonRpcParser()
        nbytes = parser.feed(m)
        self.assertNotEqual(nbytes, len(m))
        self.assertEqual(parser.error, errno.ENCODING_ERROR)

    def test_illegal_json(self):
        m = b'{ "xxxx" }'
        parser = JsonRpcParser()
        nbytes = parser.feed(m)
        self.assertNotEqual(nbytes, len(m))
        self.assertEqual(parser.error, errno.PARSE_ERROR)

    def test_illegal_jsonrpc(self):
        m = b'{ "xxxx": "yyyy" }'
        parser = JsonRpcParser()
        nbytes = parser.feed(m)
        self.assertNotEqual(nbytes, len(m))
        self.assertEqual(parser.error, errno.PARSE_ERROR)
 
    def test_maximum_message_size_exceeded(self):
        parser = JsonRpcParser()
        parser.max_message_size = 100
        message = '{{ "{0}": "{1}" }}'.format('x' * 100, 'y' * 100)
        message = message.encode('ascii')
        nbytes = parser.feed(message)
        self.assertNotEqual(nbytes, len(message))
        self.assertEqual(parser.error, errno.MESSAGE_TOO_LARGE)


def echo_app(message, endpoint, transport):
    if message.get('method') != 'echo':
        return create_error(message, 'no such method')
    return create_response(message, message['params'])

def reflect_app(message, endpoint, transport):
    if message.get('method') != 'echo':
        return
    value = endpoint.call_method(transport, 'echo', *message['params'])
    return create_response(message, value)

def notification_app():
    notifications = []
    def application(message, endpoint, transport):
        if message['id'] is None:
            notifications.append((message['method'], message['params']))
        elif message['method'] == 'get_notifications':
            return create_response(message, notifications)
    return application


class TestJsonRpc(UnitTest):

    def test_call_method(self):
        server = JsonRpcServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo', 'foo')
        self.assertEqual(result, ['foo'])

    def test_call_method_no_args(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo')
        self.assertEqual(result, [])

    def test_call_method_multiple_args(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo', 'foo', 'bar')
        self.assertEqual(result, ['foo', 'bar'])
    
    def test_call_method_error(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        exc = self.assertRaises(JsonRpcError, client.call_method, 'echo2')
        self.assertEqual(exc.args[0], errno.INVALID_REQUEST)
 
    def test_send_notification(self):
        server = JsonRpcServer(notification_app())
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        client.send_notification('notify_foo', 'foo')
        notifications = client.call_method('get_notifications')
        self.assertEqual(notifications, [['notify_foo', ['foo']]])
 
    def test_call_method_ping_pong(self):
        server = JsonRpcServer(reflect_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient(echo_app)
        client.connect(addr)
        result = client.call_method('echo', 'foo')
        self.assertEqual(result, ['foo'])

    def test_performance(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        nrequests = 0
        t1 = time.time()
        while True:
            t2 = time.time()
            if t2 - t1 > 0.5:
                break
            result = client.call_method('echo', 'foo')
            self.assertEqual(result, ['foo'])
            nrequests += 1
        print('Throughput: {0:.0f} requests/sec'.format(nrequests/(t2-t1)))

    def test_connection_limit(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        server.max_connections = 100
        clients = []
        try:
            for i in range(200):
                client = JsonRpcClient(timeout=2)
                client.connect(addr)
                clients.append(client)
        except pyuv.error.TCPError as e:
            if e.args[0] != pyuv.errno.UV_EMFILE:
                raise
            print('maximum number of file descriptors reached')
        self.assertLessEqual(len(server.clients), 100)
        for client in clients:
            client.close()
        server.close()

    def test_send_evil(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        hub = gruvi.get_hub()
        client = StreamClient()
        client.connect(addr)
        try:
            chunk = b'{' * 1024
            while True:
                client.write(chunk)
        except pyuv.error.TCPError as e:
            error = e
        self.assertIn(error.args[0], (pyuv.errno.UV_ECONNRESET, pyuv.errno.UV_EPIPE,
                                      pyuv.errno.UV_ECANCELED))

    def test_send_whitespace(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        hub = gruvi.get_hub()
        client = StreamClient()
        client.connect(addr)
        try:
            chunk = b' ' * 1024
            while True:
                client.write(chunk)
        except pyuv.error.TCPError as e:
            error = e
        self.assertIn(error.args[0], (pyuv.errno.UV_ECONNRESET, pyuv.errno.UV_EPIPE,
                                      pyuv.errno.UV_ECANCELED))

    def test_send_random(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        hub = gruvi.get_hub()
        client = StreamClient()
        client.connect(addr)
        try:
            while True:
                chunk = os.urandom(1024)
                client.write(chunk)
        except pyuv.error.TCPError as e:
            error = e
        self.assertIn(error.args[0], (pyuv.errno.UV_ECONNRESET, pyuv.errno.UV_EPIPE,
                                      pyuv.errno.UV_ECANCELED))

if __name__ == '__main__':
    unittest.main(buffer=True)
