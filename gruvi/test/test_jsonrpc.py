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
from gruvi.jsonrpc import JsonRpcParser
from gruvi.protocols import ParseError, errno
from gruvi.stream import StreamClient
from gruvi.test import UnitTest, assert_raises


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
        r = '{ "foo": "bar" }'
        ctx = split_string(r)
        assert ctx.error == 0
        assert ctx.offset == len(r)

    def test_leading_whitespace(self):
        r = ' { "foo": "bar" }'
        ctx = split_string(r)
        assert ctx.error == 0
        assert ctx.offset == len(r)
        r = ' \t\n{ "foo": "bar" }'
        ctx = split_string(r)
        assert ctx.error == 0
        assert ctx.offset == len(r)

    def test_trailing_whitespace(self):
        r = '{ "foo": "bar" } '
        ctx = split_string(r)
        assert ctx.error == 0
        assert ctx.offset == len(r)-1
        error = jsonrpc_ffi.lib.split(ctx)
        assert error == ctx.error == jsonrpc_ffi.lib.INCOMPLETE
        assert ctx.offset == len(r)

    def test_brace_in_string(self):
        r = '{ "foo": "b{r" }'
        ctx = split_string(r)
        assert ctx.error == 0
        assert ctx.offset == len(r)
        r = '{ "foo": "b}r" }'
        ctx = split_string(r)
        assert ctx.error == 0
        assert ctx.offset == len(r)

    def test_string_escape(self):
        r = r'{ "foo": "b\"}" }'
        ctx = split_string(r)
        assert ctx.error == 0
        assert ctx.offset == len(r)

    def test_error(self):
        r = ' x { "foo": "bar" }'
        ctx = split_string(r)
        assert ctx.error == jsonrpc_ffi.lib.ERROR
        assert ctx.offset == 1
        r = '[ { "foo": "bar" } ]'
        ctx = split_string(r)
        assert ctx.error == jsonrpc_ffi.lib.ERROR
        assert ctx.offset == 0

    def test_multiple(self):
        r = '{ "foo": "bar" } { "baz": "qux" }'
        ctx = split_string(r)
        assert ctx.error == 0
        assert ctx.offset == 16
        error = jsonrpc_ffi.lib.split(ctx)
        assert error == ctx.error == 0
        assert ctx.offset == len(r)

    def test_incremental(self):
        r = '{ "foo": "bar" }'
        state = 0
        ctx = jsonrpc_ffi.ffi.new('struct context *')
        for ch in r[:-1]:
            set_buffer(ctx, ch)
            error = jsonrpc_ffi.lib.split(ctx)
            assert error == ctx.error == jsonrpc_ffi.lib.INCOMPLETE
            assert ctx.offset == 1
        buf = ctx.buf = jsonrpc_ffi.ffi.new('char[]', r[-1])
        ctx.buflen = 1; ctx.offset = 0
        error = jsonrpc_ffi.lib.split(ctx)
        assert error == ctx.error == 0
        assert ctx.offset == 1

    def test_performance(self):
        chunk = '{' + 'x' * 100 + '}'
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
                assert error == ctx.error == 0
            nbytes += len(buf)
        throughput = nbytes / (1024 * 1024 * (t2 - t1))
        print('Throughput: {0:.2f} MiB/sec'.format(throughput))


class TestJsonRpcParser(UnitTest):

    def test_simple(self):
        m = '{ "id": "1", "method": "foo" }'
        parser = JsonRpcParser()
        parser.feed(m)
        msg = parser.pop_message()
        assert isinstance(msg, dict)
        assert msg == { 'id': '1', 'method': 'foo' }
        msg = parser.pop_message()
        assert msg is None

    def test_multiple(self):
        m = '{ "id": "1", "method": "foo" }' \
            '{ "id": "2", "method": "bar" }'
        parser = JsonRpcParser()
        parser.feed(m)
        msg = parser.pop_message()
        assert msg == { 'id': '1', 'method': 'foo' }
        msg = parser.pop_message()
        assert msg == { 'id': '2', 'method': 'bar' }
        msg = parser.pop_message()
        assert msg is None

    def test_whitespace(self):
        m = '  { "id": "1", "method": "foo" }' \
            '  { "id": "2", "method": "bar" }'
        parser = JsonRpcParser()
        parser.feed(m)
        msg = parser.pop_message()
        assert msg == { 'id': '1', 'method': 'foo' }
        msg = parser.pop_message()
        assert msg == { 'id': '2', 'method': 'bar' }
        msg = parser.pop_message()
        assert msg is None

    def test_incremental(self):
        m = '{ "id": "1", "method": "foo" }'
        parser = JsonRpcParser()
        for ch in m[:-1]:
            parser.feed(ch)
            assert parser.pop_message() is None
            assert parser.is_partial()
        parser.feed(m[-1])
        msg = parser.pop_message()
        assert not parser.is_partial()
        assert msg == { 'id': '1', 'method': 'foo' }

    def test_framing_error(self):
        m = 'xxx'
        parser = JsonRpcParser()
        exc = assert_raises(ParseError, parser.feed, m)
        assert exc[0] == errno.FRAMING_ERROR

    def test_encoding_error(self):
        m = '{ xxx\xff }'
        parser = JsonRpcParser()
        exc = assert_raises(ParseError, parser.feed, m)
        assert exc[0] == errno.PARSE_ERROR

    def test_illegal_json(self):
        m = '{ "xxxx" }'
        parser = JsonRpcParser()
        exc = assert_raises(ParseError, parser.feed, m)
        assert exc[0] == errno.PARSE_ERROR

    def test_illegal_jsonrpc(self):
        m = '{ "xxxx": "yyyy" }'
        parser = JsonRpcParser()
        exc = assert_raises(ParseError, parser.feed, m)
        assert exc[0] == errno.PARSE_ERROR
 
    def test_maximum_message_size_exceeded(self):
        parser = JsonRpcParser()
        parser.max_message_size = 100
        message = '{{ "{0}": "{1}" }}'.format('x' * 100, 'y' * 100)
        exc = assert_raises(ParseError, parser.feed, message)
        assert exc[0] == errno.MESSAGE_TOO_LARGE


def echo_app(message, endpoint, transport):
    if message.get('method') != 'echo':
        return create_error(message, 'no such method')
    return create_response(message, *message['params'])

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
        assert result == 'foo'

    def test_call_method_no_args(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo')
        assert result is None

    def test_call_method_multiple_args(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo', 'foo', 'bar')
        assert result == ['foo', 'bar']
    
    def test_call_method_error(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        exc = assert_raises(JsonRpcError, client.call_method, 'echo2')
        assert exc[0] == errno.INVALID_REQUEST
 
    def test_send_notification(self):
        server = JsonRpcServer(notification_app())
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient()
        client.connect(addr)
        client.send_notification('notify_foo', 'foo')
        notifications = client.call_method('get_notifications')
        assert len(notifications) == 1
        assert notifications[0] == ['notify_foo', ['foo']]
 
    def test_call_method_ping_pong(self):
        server = JsonRpcServer(reflect_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        client = JsonRpcClient(echo_app)
        client.connect(addr)
        result = client.call_method('echo', 'foo')
        assert result == 'foo'

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
            assert result == 'foo'
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
        assert len(server.clients) <= 100
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
            chunk = '{' * 1024
            while True:
                client.write(chunk)
        except pyuv.error.TCPError as e:
            error = e
        assert error.args[0] in (pyuv.errno.UV_ECONNRESET, pyuv.errno.UV_EPIPE)

    def test_send_whitespace(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.transport.getsockname()
        hub = gruvi.get_hub()
        client = StreamClient()
        client.connect(addr)
        try:
            chunk = ' ' * 1024
            while True:
                client.write(chunk)
        except pyuv.error.TCPError as e:
            error = e
        assert error.args[0] in (pyuv.errno.UV_ECONNRESET, pyuv.errno.UV_EPIPE)

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
        assert error.args[0] in (pyuv.errno.UV_ECONNRESET, pyuv.errno.UV_EPIPE)
