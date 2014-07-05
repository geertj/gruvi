#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import json

import gruvi
from gruvi import jsonrpc
from gruvi.jsonrpc import JsonRpcError, JsonRpcMethodCallError
from gruvi.jsonrpc import JsonRpcProtocol, JsonRpcClient, JsonRpcServer
from gruvi.jsonrpc_ffi import ffi as _ffi, lib as _lib
from gruvi.transports import TransportError
from support import UnitTest, unittest, MockTransport


_keepalive = None

def set_buffer(ctx, buf):
    global _keepalive  # See note in JsonRpcProtocol
    _keepalive = ctx.buf = _ffi.new('char[]', buf)
    ctx.buflen = len(buf)
    ctx.offset = 0

def split_string(s):
    ctx = _ffi.new('struct split_context *')
    set_buffer(ctx, s)
    _lib.json_split(ctx)
    return ctx


class TestJsonRpcFfi(UnitTest):

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
        error = _lib.json_split(ctx)
        self.assertEqual(error, ctx.error) == _lib.INCOMPLETE
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
        self.assertEqual(ctx.error, _lib.ERROR)
        self.assertEqual(ctx.offset, 1)
        r = b'[ { "foo": "bar" } ]'
        ctx = split_string(r)
        self.assertEqual(ctx.error, _lib.ERROR)
        self.assertEqual(ctx.offset, 0)

    def test_multiple(self):
        r = b'{ "foo": "bar" } { "baz": "qux" }'
        ctx = split_string(r)
        self.assertEqual(ctx.error, 0)
        self.assertEqual(ctx.offset, 16)
        error = _lib.json_split(ctx)
        self.assertEqual(error, ctx.error) == 0
        self.assertEqual(ctx.offset, len(r))

    def test_incremental(self):
        r = b'{ "foo": "bar" }'
        ctx = _ffi.new('struct split_context *')
        for i in range(len(r)-1):
            set_buffer(ctx, r[i:i+1])
            error = _lib.json_split(ctx)
            self.assertEqual(error, ctx.error) == _lib.INCOMPLETE
            self.assertEqual(ctx.offset, 1)
        set_buffer(ctx, r[-1:])
        error = _lib.json_split(ctx)
        self.assertEqual(error, ctx.error) == 0
        self.assertEqual(ctx.offset, 1)


class TestJsonRpcProtocol(UnitTest):

    def setUp(self):
        super(TestJsonRpcProtocol, self).setUp()
        self.transport = MockTransport()
        self.protocol = JsonRpcProtocol(self.message_handler)
        self.transport.start(self.protocol)
        self.messages = []
        self.protocols = []

    def message_handler(self, message, transport, protocol):
        self.messages.append(message)
        self.protocols.append(protocol)

    def get_messages(self):
        # run dispatcher thread so that it calls our message handler
        gruvi.sleep(0)
        return self.messages

    def test_simple(self):
        m = b'{ "id": "1", "method": "foo" }'
        proto = self.protocol
        proto.data_received(m)
        mm = self.get_messages()
        self.assertEqual(len(mm), 1)
        self.assertIsInstance(mm[0], dict)
        self.assertEqual(mm[0], {'id': '1', 'method': 'foo'})
        pp = self.protocols
        self.assertEqual(len(pp), 1)
        self.assertIs(pp[0], proto)

    def test_multiple(self):
        m = b'{ "id": "1", "method": "foo" }' \
            b'{ "id": "2", "method": "bar" }'
        proto = self.protocol
        proto.data_received(m)
        mm = self.get_messages()
        self.assertEqual(len(mm), 2)
        self.assertEqual(mm[0], {'id': '1', 'method': 'foo'})
        self.assertEqual(mm[1], {'id': '2', 'method': 'bar'})
        pp = self.protocols
        self.assertEqual(len(pp), 2)
        self.assertIs(pp[0], proto)
        self.assertIs(pp[1], proto)

    def test_whitespace(self):
        m = b'  { "id": "1", "method": "foo" }' \
            b'  { "id": "2", "method": "bar" }'
        proto = self.protocol
        proto.data_received(m)
        mm = self.get_messages()
        self.assertEqual(len(mm), 2)
        self.assertEqual(mm[0], {'id': '1', 'method': 'foo'})
        self.assertEqual(mm[1], {'id': '2', 'method': 'bar'})

    def test_incremental(self):
        m = b'{ "id": "1", "method": "foo" }'
        proto = self.protocol
        for i in range(len(m)-1):
            proto.data_received(m[i:i+1])
            self.assertEqual(self.get_messages(), [])
        proto.data_received(m[-1:])
        mm = self.get_messages()
        self.assertEqual(len(mm), 1)
        self.assertEqual(mm[0], {'id': '1', 'method': 'foo'})

    def test_framing_error(self):
        m = b'xxx'
        proto = self.protocol
        proto.data_received(m)
        self.assertEqual(self.get_messages(), [])
        self.assertIsInstance(proto._error, JsonRpcError)

    def test_encoding_error(self):
        m = b'{ xxx\xff }'
        proto = self.protocol
        proto.data_received(m)
        self.assertEqual(self.get_messages(), [])
        self.assertIsInstance(proto._error, JsonRpcError)

    def test_illegal_json(self):
        m = b'{ "xxxx" }'
        proto = self.protocol
        proto.data_received(m)
        self.assertEqual(self.get_messages(), [])
        self.assertIsInstance(proto._error, JsonRpcError)

    def test_illegal_jsonrpc(self):
        m = b'{ "xxxx": "yyyy" }'
        proto = self.protocol
        proto.data_received(m)
        self.assertEqual(self.get_messages(), [])
        self.assertIsInstance(proto._error, JsonRpcError)

    def test_maximum_message_size_exceeded(self):
        proto = self.protocol
        proto.set_read_buffer_limits(100)
        message = {'id': 1, 'method': 'foo', 'params': ['x'*100]}
        self.assertEqual(jsonrpc.check_message(message), '1.0')
        message = json.dumps(message).encode('utf8')
        self.assertGreater(len(message), proto._read_buffer_high)
        proto.data_received(message)
        self.assertEqual(self.get_messages(), [])
        self.assertIsInstance(proto._error, JsonRpcError)

    def test_flow_control(self):
        # Write more bytes than the protocol buffers. Flow control should kick
        # in and alternate scheduling of the producer and the consumer.
        proto = self.protocol
        proto.read_buffer_size = 100
        message = b'{ "id": 1, "method": "foo"}'
        for i in range(1000):
            proto.data_received(message)
            if not proto._reading:
                gruvi.sleep(0)  # run dispatcher
            self.assertTrue(proto._reading)
        mm = self.get_messages()
        self.assertEqual(len(mm), 1000)
        message = json.loads(message.decode('utf8'))
        for m in mm:
            self.assertEqual(m, message)


def echo_app(message, transport, protocol):
    if message.get('method') != 'echo':
        message = jsonrpc.create_error(message, jsonrpc.METHOD_NOT_FOUND)
    else:
        message = jsonrpc.create_response(message, message['params'])
    protocol.send_message(message)

def reflect_app(message, transport, protocol):
    if message.get('method') != 'echo':
        return
    value = protocol.call_method('echo', *message['params'])
    message = jsonrpc.create_response(message, value)
    protocol.send_message(message)

def notification_app():
    notifications = []
    def application(message, transport, protocol):
        if message.get('id') is None:
            notifications.append((message['method'], message['params']))
        elif message['method'] == 'get_notifications':
            message = jsonrpc.create_response(message, notifications)
            protocol.send_message(message)
    return application


class TestJsonRpc(UnitTest):

    def test_errno(self):
        code = jsonrpc.SERVER_ERROR
        self.assertIsInstance(code, int)
        name = jsonrpc.errorcode[code]
        self.assertIsInstance(name, str)
        self.assertEqual(getattr(jsonrpc, name), code)
        desc = jsonrpc.strerror(code)
        self.assertIsInstance(desc, str)

    def test_call_method_tcp(self):
        server = JsonRpcServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo', 'foo')
        self.assertEqual(result, ['foo'])
        server.close()
        client.close()

    def test_call_method_pipe(self):
        server = JsonRpcServer(echo_app)
        server.listen(self.pipename(abstract=True))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo', 'foo')
        self.assertEqual(result, ['foo'])
        server.close()
        client.close()

    def test_call_method_ssl(self):
        server = JsonRpcServer(echo_app)
        context = self.get_ssl_context()
        server.listen(('localhost', 0), ssl=context)
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr, ssl=context)
        result = client.call_method('echo', 'foo')
        self.assertEqual(result, ['foo'])
        server.close()
        client.close()

    def test_call_method_no_args(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo')
        self.assertEqual(result, [])
        server.close()
        client.close()

    def test_call_method_multiple_args(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        result = client.call_method('echo', 'foo', 'bar')
        self.assertEqual(result, ['foo', 'bar'])
        server.close()
        client.close()

    def test_call_method_error(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        exc = self.assertRaises(JsonRpcError, client.call_method, 'echo2')
        self.assertIsInstance(exc, JsonRpcMethodCallError)
        self.assertIsInstance(exc.error, dict)
        self.assertEqual(exc.error['code'], jsonrpc.METHOD_NOT_FOUND)
        server.close()
        client.close()

    def test_send_notification(self):
        server = JsonRpcServer(notification_app())
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        client.send_notification('notify_foo', 'foo')
        notifications = client.call_method('get_notifications')
        self.assertEqual(notifications, [['notify_foo', ['foo']]])
        server.close()
        client.close()

    def test_call_method_ping_pong(self):
        server = JsonRpcServer(reflect_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient(echo_app)
        client.connect(addr)
        result = client.call_method('echo', 'foo')
        self.assertEqual(result, ['foo'])
        server.close()
        client.close()

    def test_send_evil(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        transport = client.connection[0]
        exc = None
        try:
            chunk = b'{' * 1024
            while True:
                transport.write(chunk)
                gruvi.sleep(0)
        except Exception as e:
            exc = e
        self.assertIsInstance(exc, TransportError)
        server.close()
        client.close()

    def test_send_whitespace(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        transport = client.connection[0]
        exc = None
        try:
            chunk = b' ' * 1024
            while True:
                transport.write(chunk)
                gruvi.sleep(0)
        except Exception as e:
            exc = e
        self.assertIsInstance(exc, TransportError)
        server.close()
        client.close()

    def test_send_random(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        transport = client.connection[0]
        exc = None
        try:
            while True:
                chunk = os.urandom(1024)
                transport.write(chunk)
                gruvi.sleep(0)
        except Exception as e:
            exc = e
        self.assertIsInstance(exc, TransportError)
        server.close()
        client.close()

    def test_connection_limit(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        server.max_connections = 10
        clients = []
        exc = None
        try:
            for i in range(15):
                client = JsonRpcClient(timeout=2)
                client.connect(addr)
                client.call_method('echo')
                clients.append(client)
        except Exception as e:
            exc = e
        self.assertIsInstance(exc, TransportError)
        self.assertLessEqual(len(server.connections), server.max_connections)
        for client in clients:
            client.close()
        server.close()


if __name__ == '__main__':
    unittest.main()
