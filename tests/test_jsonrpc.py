#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import json
import unittest
import six

import gruvi
from gruvi import jsonrpc
from gruvi.jsonrpc import JsonRpcError, JsonRpcVersion
from gruvi.jsonrpc import JsonRpcProtocol, JsonRpcClient, JsonRpcServer
from gruvi.jsonrpc_ffi import ffi as _ffi, lib as _lib
from gruvi.transports import TransportError
from support import UnitTest, MockTransport


_keepalive = None

def set_buffer(ctx, buf):
    global _keepalive  # See note in JsonRpcProtocol
    _keepalive = ctx.buf = _ffi.from_buffer(buf)
    ctx.buflen = len(buf)
    ctx.offset = 0

def split_string(s):
    ctx = _ffi.new('struct split_context *')
    set_buffer(ctx, s)
    _lib.json_split(ctx)
    return ctx


JsonRpcProtocol.default_version = '1.0'


class TestJsonSplitter(UnitTest):

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


class TestJsonRpcV1(UnitTest):

    def setUp(self):
        super(TestJsonRpcV1, self).setUp()
        self.version = JsonRpcVersion.create('1.0')

    def test_check_request(self):
        v = self.version
        msg = {'id': 1, 'method': 'foo', 'params': []}
        self.assertEqual(v.check_message(msg), jsonrpc.REQUEST)
        msg = {'id': None, 'method': 'foo', 'params': []}
        self.assertEqual(v.check_message(msg), jsonrpc.REQUEST)

    def test_check_request_missing_id(self):
        v = self.version
        msg = {'method': 'foo', 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_request_missing_method(self):
        v = self.version
        msg = {'id': 1, 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_request_illegal_method(self):
        v = self.version
        msg = {'id': 1, 'method': None, 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'method': 1, 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'method': {}, 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'method': [], 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'method': [1], 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_request_missing_params(self):
        v = self.version
        msg = {'id': 1, 'method': 'foo'}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_request_illegal_params(self):
        v = self.version
        msg = {'id': 1, 'method': 'foo', 'params': None}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'method': 'foo', 'params': 1}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'method': 'foo', 'params': 'foo'}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'method': 'foo', 'params': {}}

    def test_check_request_extraneous_fields(self):
        v = self.version
        msg = {'id': 1, 'method': 'foo', 'params': [], 'bar': 'baz'}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response(self):
        v = self.version
        msg = {'id': 1, 'result': 'foo', 'error': None}
        self.assertEqual(v.check_message(msg), jsonrpc.RESPONSE)

    def test_check_response_null_result(self):
        v = self.version
        msg = {'id': 1, 'result': None, 'error': None}
        self.assertEqual(v.check_message(msg), jsonrpc.RESPONSE)

    def test_check_response_error(self):
        v = self.version
        msg = {'id': 1, 'result': None, 'error': {'code': 1}}
        self.assertEqual(v.check_message(msg), jsonrpc.RESPONSE)

    def test_check_response_missing_id(self):
        v = self.version
        msg = {'result': 'foo', 'error': None}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_missing_result(self):
        v = self.version
        msg = {'id': 1, 'error': None}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_missing_error(self):
        v = self.version
        msg = {'id': 1, 'result': None}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_illegal_error(self):
        v = self.version
        msg = {'id': 1, 'result': None, 'error': 1}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'result': None, 'error': 'foo'}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'id': 1, 'result': None, 'error': []}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_result_error_both_set(self):
        v = self.version
        msg = {'id': 1, 'result': 1, 'error': 0}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_extraneous_fields(self):
        v = self.version
        msg = {'id': 1, 'result': 1, 'error': None, 'bar': 'baz'}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_create_request(self):
        v = self.version
        msg = v.create_request('foo', [])
        self.assertIsInstance(msg['id'], six.string_types)
        self.assertEqual(msg['method'], 'foo')
        self.assertEqual(msg['params'], [])
        self.assertEqual(len(msg), 3)

    def test_create_request_notification(self):
        v = self.version
        msg = v.create_request('foo', [], notification=True)
        self.assertIsNone(msg['id'])
        self.assertEqual(msg['method'], 'foo')
        self.assertEqual(msg['params'], [])
        self.assertEqual(len(msg), 3)

    def test_create_response(self):
        v = self.version
        req = {'id': 'gruvi.0'}
        msg = v.create_response(req, 1)
        self.assertEqual(msg['id'], req['id'])
        self.assertEqual(msg['result'], 1)
        self.assertIsNone(msg['error'])
        self.assertEqual(len(msg), 3)

    def test_create_response_null_result(self):
        v = self.version
        req = {'id': 'gruvi.0'}
        msg = v.create_response(req, None)
        self.assertEqual(msg['id'], req['id'])
        self.assertIsNone(msg['result'])
        self.assertIsNone(msg['error'])
        self.assertEqual(len(msg), 3)

    def test_create_response_error(self):
        v = self.version
        req = {'id': 'gruvi.0'}
        msg = v.create_response(req, error={'code': 1})
        self.assertEqual(msg['id'], req['id'])
        self.assertIsNone(msg['result'])
        self.assertEqual(msg['error'], {'code': 1})
        self.assertEqual(len(msg), 3)


class TestJsonRpcV2(UnitTest):

    def setUp(self):
        super(TestJsonRpcV2, self).setUp()
        self.version = JsonRpcVersion.create('2.0')

    def test_check_request(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'foo', 'params': []}
        self.assertEqual(v.check_message(msg), jsonrpc.REQUEST)
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'foo', 'params': {}}
        self.assertEqual(v.check_message(msg), jsonrpc.REQUEST)

    def test_check_request_notification(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'method': 'foo', 'params': []}
        self.assertEqual(v.check_message(msg), jsonrpc.REQUEST)
        msg = {'jsonrpc': '2.0', 'method': 'foo', 'params': {}}
        self.assertEqual(v.check_message(msg), jsonrpc.REQUEST)

    def test_check_request_missing_version(self):
        v = self.version
        msg = {'id': 1, 'method': 'foo', 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_request_missing_method(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_request_illegal_method(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': None, 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': 1, 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': {}, 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': [], 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': [1], 'params': []}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_request_missing_params(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'foo'}
        self.assertEqual(v.check_message(msg), jsonrpc.REQUEST)

    def test_check_request_illegal_params(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'foo', 'params': None}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'foo', 'params': 1}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'foo', 'params': 'foo'}

    def test_check_request_extraneous_fields(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'foo', 'params': [], 'bar': 'baz'}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'result': 'foo'}
        self.assertEqual(v.check_message(msg), jsonrpc.RESPONSE)

    def test_check_response_null_result(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'result': None}
        self.assertEqual(v.check_message(msg), jsonrpc.RESPONSE)

    def test_check_response_error(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 1}}
        self.assertEqual(v.check_message(msg), jsonrpc.RESPONSE)

    def test_check_response_missing_id(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'result': 'foo'}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_null_id(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': None, 'result': 'foo'}
        self.assertEqual(v.check_message(msg), jsonrpc.RESPONSE)

    def test_check_response_error_missing_id(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'error': {'code': 10}}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_error_null_id(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': None, 'error': {'code': 1}}
        self.assertEqual(v.check_message(msg), jsonrpc.RESPONSE)

    def test_check_response_missing_result_and_error(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_illegal_error(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'error': 1}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'error': 'foo'}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'error': []}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_result_error_both_present(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'result': None, 'error': None}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'result': 1, 'error': None}
        self.assertRaises(ValueError, v.check_message, msg)
        msg = {'jsonrpc': '2.0', 'id': 1, 'result': None, 'error': {'code': 10}}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_check_response_extraneous_fields(self):
        v = self.version
        msg = {'jsonrpc': '2.0', 'id': 1, 'result': 1, 'error': None, 'bar': 'baz'}
        self.assertRaises(ValueError, v.check_message, msg)

    def test_create_request(self):
        v = self.version
        msg = v.create_request('foo', [])
        self.assertEqual(msg['jsonrpc'], '2.0')
        self.assertIsInstance(msg['id'], six.string_types)
        self.assertEqual(msg['method'], 'foo')
        self.assertEqual(msg['params'], [])
        self.assertEqual(len(msg), 4)

    def test_create_request_notification(self):
        v = self.version
        msg = v.create_request('foo', [], notification=True)
        self.assertEqual(msg['jsonrpc'], '2.0')
        self.assertNotIn('id', msg)
        self.assertEqual(msg['method'], 'foo')
        self.assertEqual(msg['params'], [])
        self.assertEqual(len(msg), 3)

    def test_create_response(self):
        v = self.version
        req = {'id': 'gruvi.0'}
        msg = v.create_response(req, 1)
        self.assertEqual(msg['jsonrpc'], '2.0')
        self.assertEqual(msg['id'], req['id'])
        self.assertEqual(msg['result'], 1)
        self.assertNotIn('error', msg)
        self.assertEqual(len(msg), 3)

    def test_create_response_null_result(self):
        v = self.version
        req = {'id': 'gruvi.0'}
        msg = v.create_response(req, None)
        self.assertEqual(msg['jsonrpc'], '2.0')
        self.assertEqual(msg['id'], req['id'])
        self.assertIsNone(msg['result'])
        self.assertNotIn('error', msg)
        self.assertEqual(len(msg), 3)

    def test_create_response_error(self):
        v = self.version
        req = {'id': 'gruvi.0'}
        msg = v.create_response(req, error={'code': 1})
        self.assertEqual(msg['jsonrpc'], '2.0')
        self.assertEqual(msg['id'], req['id'])
        self.assertNotIn('result', msg)
        self.assertEqual(msg['error'], {'code': 1})
        self.assertEqual(len(msg), 3)


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
        m = b'{ "id": "1", "method": "foo", "params": [] }'
        proto = self.protocol
        proto.data_received(m)
        mm = self.get_messages()
        self.assertEqual(len(mm), 1)
        self.assertIsInstance(mm[0], dict)
        self.assertEqual(mm[0], {'id': '1', 'method': 'foo', 'params': []})
        pp = self.protocols
        self.assertEqual(len(pp), 1)
        self.assertIs(pp[0], proto)

    def test_multiple(self):
        m = b'{ "id": "1", "method": "foo", "params": [] }' \
            b'{ "id": "2", "method": "bar", "params": [] }'
        proto = self.protocol
        proto.data_received(m)
        mm = self.get_messages()
        self.assertEqual(len(mm), 2)
        self.assertEqual(mm[0], {'id': '1', 'method': 'foo', 'params': []})
        self.assertEqual(mm[1], {'id': '2', 'method': 'bar', 'params': []})
        pp = self.protocols
        self.assertEqual(len(pp), 2)
        self.assertIs(pp[0], proto)
        self.assertIs(pp[1], proto)

    def test_whitespace(self):
        m = b'  { "id": "1", "method": "foo", "params": [] }' \
            b'  { "id": "2", "method": "bar", "params": [] }'
        proto = self.protocol
        proto.data_received(m)
        mm = self.get_messages()
        self.assertEqual(len(mm), 2)
        self.assertEqual(mm[0], {'id': '1', 'method': 'foo', 'params': []})
        self.assertEqual(mm[1], {'id': '2', 'method': 'bar', 'params': []})

    def test_incremental(self):
        m = b'{ "id": "1", "method": "foo", "params": [] }'
        proto = self.protocol
        for i in range(len(m)-1):
            proto.data_received(m[i:i+1])
            self.assertEqual(self.get_messages(), [])
        proto.data_received(m[-1:])
        mm = self.get_messages()
        self.assertEqual(len(mm), 1)
        self.assertEqual(mm[0], {'id': '1', 'method': 'foo', "params": []})

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
        proto.max_message_size = 100
        message = {'id': 1, 'method': 'foo', 'params': ['x'*100]}
        message = json.dumps(message).encode('utf8')
        self.assertGreater(len(message), proto.max_message_size)
        proto.data_received(message)
        self.assertEqual(self.get_messages(), [])
        self.assertIsInstance(proto._error, JsonRpcError)

    def test_flow_control(self):
        # Write more messages than the protocol is willing to pipeline. Flow
        # control should kick in and alternate scheduling of the producer and
        # the consumer.
        proto, trans = self.protocol, self.transport
        self.assertTrue(trans._reading)
        proto.max_pipeline_size = 10
        message = b'{ "id": 1, "method": "foo", "params": [] }'
        interrupted = 0
        for i in range(1000):
            proto.data_received(message)
            if not trans._reading:
                interrupted += 1
                gruvi.sleep(0)  # run dispatcher
            self.assertTrue(trans._reading)
        mm = self.get_messages()
        self.assertEqual(len(mm), 1000)
        self.assertEqual(interrupted, 100)
        message = json.loads(message.decode('utf8'))
        for m in mm:
            self.assertEqual(m, message)


def echo_app(message, transport, protocol):
    if message.get('method') != 'echo':
        protocol.send_response(message, error={'code': jsonrpc.METHOD_NOT_FOUND})
    else:
        protocol.send_response(message, message['params'])

def reflect_app(message, transport, protocol):
    if message.get('method') != 'echo':
        return
    value = protocol.call_method('echo', *message['params'])
    protocol.send_response(message, value)

def notification_app():
    notifications = []
    def application(message, transport, protocol):
        if message.get('id') is None:
            notifications.append((message['method'], message['params']))
        elif message['method'] == 'get_notifications':
            protocol.send_response(message, notifications)
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
        self.assertIsInstance(exc, JsonRpcError)
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
        exc = None
        try:
            chunk = b'{' * 1024
            while True:
                client.transport.write(chunk)
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
        exc = None
        try:
            chunk = b' ' * 1024
            while True:
                client.transport.write(chunk)
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
        exc = None
        try:
            while True:
                chunk = os.urandom(1024)
                client.transport.write(chunk)
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
        server.max_connections = 2
        clients = []
        exc = None
        try:
            for i in range(3):
                client = JsonRpcClient(timeout=2)
                client.connect(addr)
                client.call_method('echo')
                clients.append(client)
        except Exception as e:
            exc = e
        self.assertIsInstance(exc, TransportError)
        self.assertEqual(len(server.connections), server.max_connections)
        for client in clients:
            client.close()
        server.close()


if __name__ == '__main__':
    unittest.main()
