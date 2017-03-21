#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

"""
The :mod:`gruvi.jsonrpc` module implements a JSON-RPC client and server.

There are two main version of JSON-RPC: version 1.0 and version 2.0. These
version are not compatible with each other. Fortunately though, it is possible
to distinguish a version 1.0 from a version 2.0 message, and also the RPC model
in both versions is identical. This module therefore implements both versions
at the same time, in the following way:

 * A reply to an incoming message will always be of the same version as the
   incoming message.
 * A message originated by this module will use version 2.0 by default, but
   the default can be changed.

The "batch" feature of version 2.0 is not supported. It more relevant for
JSON-RPC over HTTP rather for that clients and servers that operate directly on
top of a connection.

This module provides two main classes: :class:`JsonRpcClient` and
:class:`JsonRpcServer`. The difference is merely who initiates the connection
at the transport level. The JSON-RPC protocol itself does not distinguish
between clients and servers.

Both the client and the server can get incoming messages. These may be method
calls (more common for servers), or notifications (in both cases). These
incoming messages may be handled by providing a message handler. Providing a
messasge handler is mandatory for a server while it's optional for a client.
Note that for getting regular or error returns to method calls it is not
required to have a message handler. These are taken care of by the protocol
implementation itself.

The signature of the message handler is: ``message_handler(message,
protocol)``.  Here, the *message* argument is a dictionary containing the
parsed JSON-RPC message, while *protocol* is the protocol instance for the
connection. The message handler is entirely responsible for dealing with the
message including sending a response if applicable.

Message handlers run in a separate "distpacher" fiber, one per connection. This
means that a client will have at most one dispatcher fiber, while a server will
have exactly one fiber per connection. The fact that message handlers run in a
separate fiber allows them to call into a switchpoint.
"""

from __future__ import absolute_import, print_function

import json
import functools
import six

from . import compat
from .hub import switchpoint, switch_back
from .util import delegate_method
from .transports import TransportError
from .protocols import ProtocolError, MessageProtocol
from .stream import Stream
from .endpoints import Client, Server
from .address import saddr
from .jsonrpc_ffi import lib, ffi

__all__ = ['JsonRpcError', 'JsonRpcMethodCallError', 'JsonRpcProtocol',
           'JsonRpcClient', 'JsonRpcServer']


# JSON-RPC v2.0 error codes

errorcode = {}
_jsonrpc_errlist = {}

def add_error(code, name, message):
    globals()[name] = code
    errorcode[code] = name
    _jsonrpc_errlist[code] = message

add_error(-32000, 'SERVER_ERROR', 'Server error')
add_error(-32600, 'INVALID_REQUEST', 'Invalid request')
add_error(-32601, 'METHOD_NOT_FOUND', 'Method not found')
add_error(-32602, 'INVALID_PARAMS', 'Invalid parameters')
add_error(-32603, 'INTERNAL_ERROR', 'Internal error')
add_error(-32700, 'PARSE_ERROR', 'Parse error')

del add_error

def strerror(code):
    return _jsonrpc_errlist.get(code, 'No error description available')


class JsonRpcError(ProtocolError):
    """Exception that is raised in case of JSON-RPC protocol errors."""


class JsonRpcMethodCallError(JsonRpcError):
    """Exception that is raised when a error reply is received for a JSON-RPC
    method call."""

    def __init__(self, message, error):
        super(JsonRpcMethodCallError, self).__init__(message)
        self._error = error

    @property
    def error(self):
        return self._error


Absent = object()

def check_message_v1(message):
    """Validate a JSON-RPC v1 message."""
    msgid = message.get('id', Absent)
    if msgid is Absent:
        return
    method = message.get('method', Absent)
    if method is Absent:
        result = message.get('result', Absent)
        error = message.get('error', Absent)
        if result is Absent or error is Absent or \
                error is not None and not isinstance(error, dict) or \
                result is not None and error is not None or \
                len(message) != 3:
            return
        return 'response' if error is None else 'error'
    elif isinstance(method, six.string_types):
        params = message.get('params', Absent)
        if params is Absent or not isinstance(params, list) or \
                len(message) != 3:
            return
        return 'notification' if msgid is None else 'methodcall'

def check_message_v2(message):
    """Validate a JSON-RPC v2 message."""
    version = message.get('jsonrpc')
    if version != '2.0':
        return
    msgid = message.get('id', Absent)
    if msgid is not Absent and not isinstance(msgid, six.string_types) and \
                not isinstance(msgid, (int, float)):
        return
    method = message.get('method', Absent)
    if method is Absent:
        result = message.get('result', Absent)
        error = message.get('error', Absent)
        if msgid is Absent or \
                error is not Absent and not isinstance(error, dict) or \
                (result is Absent) == (error is Absent) or \
                len(message) != 3:
            return
        return 'response' if result else 'error'
    elif isinstance(method, six.string_types):
        params = message.get('params', Absent)
        if params is not Absent and not isinstance(params, (dict, list)) or \
                len(message) != 2 + (msgid is not Absent) + (params is not Absent):
            return
        return 'methodcall' if msgid is Absent else 'notification'


_last_request_id = 0

def _get_request_id():
    global _last_request_id
    _last_request_id += 1
    reqid = 'gruvi.{}'.format(_last_request_id)
    return reqid

def create_request(method, args=[], version='2.0'):
    """Create a JSON-RPC request."""
    msg = {'id': _get_request_id(), 'method': method, 'params': args}
    if version == '2.0':
        msg['jsonrpc'] = version
    return msg

def create_response(request, result):
    """Create a JSON-RPC response message."""
    msg = {'id': request['id'], 'result': result}
    version = request.get('jsonrpc', '1.0')
    if version == '1.0':
        msg['error'] = None
    elif version == '2.0':
        msg['jsonrpc'] = version
    return msg

def create_error(request, code=None, message=None, data=None, error=None):
    """Create a JSON-RPC error response message."""
    if code is None and error is None:
        raise ValueError('either "code" or "error" must be set')
    msg = {'id': request and request.get('id')}
    if code:
        error = {'code': code}
        error['message'] = message or strerror(code)
        if data:
            error['data'] = data
    msg['error'] = error
    version = request.get('jsonrpc', '1.0')
    if version == '1.0':
        msg['result'] = None
    elif version == '2.0':
        msg['jsonrpc'] = version
    return msg

def create_notification(method, args=[], version='2.0'):
    """Create a JSON-RPC notification message."""
    msg = {'method': method, 'params': args}
    if version == '1.0':
        msg['id'] = None
    elif version == '2.0':
        msg['jsonrpc'] = version
    return msg


class JsonRpcProtocol(MessageProtocol):
    """JSON-RPC protocol."""

    # Any message larger than this and the connection is dropped.
    # This can be increased, but do note that message are kept in memory until
    # they are dispatched.
    max_message_size = 65536

    def __init__(self, message_handler=None, version='2.0', timeout=None):
        if version not in ('1.0', '2.0'):
            raise ValueError('version: must be "1.0" or "2.0"')
        super(JsonRpcProtocol, self).__init__(message_handler, timeout=timeout)
        self._version = version
        self._buffer = bytearray()
        self._context = ffi.new('struct split_context *')
        self._method_calls = {}
        if version == '1.0':
            self._check_message = check_message_v1
        else:
            self._check_message = check_message_v2

    def connection_made(self, transport):
        # Protocol callback
        super(JsonRpcProtocol, self).connection_made(transport)
        self._writer = Stream(transport, 'w')

    def connection_lost(self, exc):
        # Protocol callback
        super(JsonRpcProtocol, self).connection_lost(exc)
        for switcher in self._method_calls.values():
            switcher.throw(TransportError('connection lost'))
        self._method_calls.clear()

    def data_received(self, data):
        # Protocol callback
        offset = 0
        self._context.buf = ffi.from_buffer(data)
        self._context.buflen = len(data)
        self._context.offset = 0
        # Use the CFFI JSON splitter to delineate JSON messages in the input
        # stream. Then decode, parse and check it.
        while offset != len(data):
            error = lib.json_split(self._context)
            if error and error != lib.INCOMPLETE:
                self._error = JsonRpcError('json_split() error: {}'.format(error))
                break
            size = len(self._buffer) + self._context.offset - offset
            if size > self.max_message_size:
                self._error = JsonRpcError('message too large')
                break
            if error == lib.INCOMPLETE:
                self._buffer.extend(data[offset:])
                break
            chunk = data[offset:self._context.offset]
            if self._buffer:
                self._buffer.extend(chunk)
                chunk = self._buffer
                self._buffer = bytearray()
            try:
                chunk = chunk.decode('utf8')
                message = json.loads(chunk)
            except UnicodeDecodeError as e:
                self._error = JsonRpcError('UTF-8 decoding error: {!s}'.format(e))
                break
            except ValueError as e:
                self._error = JsonRpcError('Illegal JSON-RPC message: {!s}'.format(e))
                break
            mtype = self._check_message(message)
            if not mtype:
                self._error = JsonRpcError('Invalid JSON-RPC message')
                break
            peername = self._transport.get_extra_info('peername', '(n/a)')
            self._log.debug('incoming {} from peer {}', mtype, peername)
            self._log.trace('\n\n{}\n', chunk)
            # Now route the message to its correct destination
            if mtype in ('response', 'error') and message['id'] in self._method_calls:
                # Response to a method call issues through call_method()
                switcher = self._method_calls.pop(message['id'])
                switcher(message)
            elif self._message_handler:
                # Queue to the dispatcher
                self._queue.put_nowait(message)
                self._maybe_pause_transport()
            else:
                self._log.warning('inbound {} but no message handler', mtype)
            offset = self._context.offset
        if self._error:
            self._transport.close()
            return

    @switchpoint
    def send_message(self, message):
        """Send a JSON-RPC message.

        The *message* argument must be a dictionary, and must be a valid
        JSON-RPC message.
        """
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._transport is None:
            raise JsonRpcError('not connected')
        self._check_message(message)
        serialized = json.dumps(message, indent=2)
        self._writer.write(serialized.encode('utf-8'))

    @switchpoint
    def send_notification(self, method, *args):
        """Send a JSON-RPC notification.

        The notification *method* is sent with positional arguments *args*.
        """
        message = create_notification(method, args, version=self._version)
        self.send_message(message)

    @switchpoint
    def call_method(self, method, *args, **kwargs):
        """Call a JSON-RPC method and wait for its result.

        The method *method* is called with positional arguments *args*. On
        success, the ``'result'`` attribute of the JSON-RPC response is
        returned. On error, an exception is raised.

        This method also takes a an optional *timeout* keyword argument that
        overrides the default timeout passed to the constructor.
        """
        timeout = kwargs.get('timeout', self._timeout)
        message = create_request(method, args, version=self._version)
        msgid = message['id']
        try:
            with switch_back(timeout) as switcher:
                self._method_calls[msgid] = switcher
                self.send_message(message)
                args, _ = self._hub.switch()
        finally:
            self._method_calls.pop(msgid, None)
        response = args[0]
        assert response['id'] == msgid
        error = response.get('error')
        if error:
            raise JsonRpcMethodCallError('error calling {!r} method'.format(method), error)
        return response.get('result')


class JsonRpcClient(Client):
    """A JSON-RPC client."""

    def __init__(self, message_handler=None, version='2.0', timeout=30):
        """
        The *message_handler* argument specifies an optional JSON-RPC message
        handler. You need to use a message handler if you want to listen to
        notifications or you want to implement server-to-client method calls.
        If provided, the message handler it must be a callable with signature
        ``message_handler(message, transport, protocol)``.

        The *version* argument specifies the JSON-RPC version to use. The
        *timeout* argument specifies the default timeout in seconds.
        """
        protocol_factory = functools.partial(JsonRpcProtocol, message_handler, version)
        super(JsonRpcClient, self).__init__(protocol_factory, timeout)

    protocol = Client.protocol

    delegate_method(protocol, JsonRpcProtocol.send_message)
    delegate_method(protocol, JsonRpcProtocol.send_notification)
    delegate_method(protocol, JsonRpcProtocol.call_method)


class JsonRpcServer(Server):
    """A JSON-RPC server."""

    max_connections = 1000

    def __init__(self, message_handler, version='2.0', timeout=30):
        """
        The *message_handler* argument specifies the JSON-RPC message handler.
        It must be a callable with signature ``message_handler(message,
        transport, protocol)``. The message handler is called in a separate
        dispatcher fiber (one per connection).

        The *version* argument specifies the default JSON-RPC version. The
        *timeout* argument specifies the default timeout.
        """

        protocol_factory = functools.partial(JsonRpcProtocol, message_handler, version)
        super(JsonRpcServer, self).__init__(protocol_factory, timeout=timeout)
