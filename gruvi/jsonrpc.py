#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

"""
This module implements a JSON-RPC verson 1 client and server.

The JSON-RPC protocol itself does not distinguish between client and servers.
This module does provide two different classes however, one for a client and
one for a server. The only difference between them is who initiates the
connection: the server has a ``listen()`` method and the client has a
``connect()`` method.

Both the client and the server can get incoming messages. These may be method
calls (more common for servers), or notifications. These incoming messages may
be handled by providing the client or server with a message handler.

The signature of the message handler is: ``message_handler(message, protocol,
client)``. Here, the *message* argument is a dictionary containing the parsed
JSON-RPC message.  The *protocol* is either the client or the server instance,
while the *client* is the transport this message was received on. In case of a
server socket, *client* will be an element of :attr:`JsonRpcServer.clients`, in
case of a client socket, *client* will :attr:`JsonRpcClient.transport`.

The return value of the message handler may be ``None``, or a dictionary
containing the message to send back. This will typically be a reply to a method
call, but this is not required.

Message handlers runs in their own fiber. This allows a message handler to call
into a switchpoint. There will be one fiber for every connection. So on the
client side there will be at most one fiber, and on the server side as many as
there are connections.
"""

from __future__ import absolute_import, print_function

import json

from . import hub, error, protocols, jsonrpc_ffi, compat
from .hub import switchpoint
from .util import docfrom
from .protocols import ProtocolError

__all__ = ['JsonRpcError', 'JsonRpcClient', 'JsonRpcServer']


class errno(object):
    """JSON-RPC v2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_ERROR = -32000

    errlist = {
        PARSE_ERROR: 'Parse error',
        INVALID_REQUEST: 'Invalid request',
        METHOD_NOT_FOUND: 'Method not found',
        INVALID_PARAMS: 'Invalid params',
        INTERNAL_ERROR: 'Internal error',
        SERVER_ERROR: 'Server error'
    }

    errorcode = dict((k,v) for k,v in locals().items() if k.isupper())

    @classmethod
    def strerror(cls, code):
        return cls.errlist.get(code, 'Unknown error')


class JsonRpcError(ProtocolError):
    """Exception that is raised in case of JSON-RPC protocol errors."""


_allowed_keys = frozenset(('jsonrpc', 'id', 'method', 'params', 'result', 'error'))

def check_message(message):
    """Validate a JSON-RPC message.
    
    The message must be a dictionary. Return True if the message is valid,
    False otherwise.
    """
    if not isinstance(message, dict):
        return False
    if 'jsonrpc' in message and message['jsonrpc'] != '2.0':
        return False
    if 'method' in message:
        # Request or notification
        if not isinstance(message['method'], compat.string_types):
            return False
        if not isinstance(message.get('params', []), (list, tuple)):
            return False
        if message.get('result') or message.get('error'):
            return False
    else:
        # Success or error response
        if message.get('id') is None:
            return False
        if 'result' not in message and 'error' not in message or \
                    message.get('result') is not None and \
                        message.get('error') is not None:
            return False
        if 'params' in message:
            return False
    if set(message) - _allowed_keys:
        return False
    return True


_last_request_id = 0

def _get_request_id():
    global _last_request_id
    _last_request_id += 1
    reqid = 'gruvi.{0}'.format(_last_request_id)
    return reqid


def create_request(method, args, version='1.0'):
    """Create a JSON-RPC request."""
    msg = { 'id': _get_request_id(), 'method': method, 'params': args }
    if version == '2.0':
        msg['jsonrpc'] = version
    return msg

def create_response(request, result):
    """Create a JSON-RPC response message."""
    msg = { 'id': request['id'], 'result': result }
    if 'jsonrpc' not in request:
        msg['error'] = None
    elif request['jsonrpc'] == '2.0':
        msg['jsonrpc'] = request['jsonrpc']
    return msg

def create_error(request, code=None, message=None, data=None, error=None):
    """Create a JSON-RPC error response message."""
    if code is None and error is None:
        raise ValueError('either "code" or "error" must be set')
    msg = { 'id': request['id'] }
    if code:
        error = { 'code': code }
        error['message'] = errno.strerror(code)
        if data:
            error['data'] = data
    msg['error'] = error
    if 'jsonrpc' not in request:
        msg['result'] = None
    elif request['jsonrpc'] == '2.0':
        msg['jsonrpc'] = version
    return msg

def create_notification(method, args, version='1.0'):
    """Create a JSON-RPC notification message."""
    msg = { 'method': method, 'params': args }
    if version == '1.0':
        msg['id'] = None
    elif version == '2.0':
        msg['jsonrpc'] = version
    return msg


class JsonRpcParser(protocols.Parser):
    """A JSON-RPC Parser."""

    max_message_size = 128*1024

    def __init__(self):
        super(JsonRpcParser, self).__init__()
        self._buffer = bytearray()
        self._context = jsonrpc_ffi.ffi.new('struct context *')

    def feed(self, buf):
        # len(buf) == 0 means EOF received
        if len(buf) == 0:
            if len(self._buffer) > 0:
                self._error = protocols.errno.FRAMING_ERROR
                self._error_message = 'partial message'
                return -1
            return 0
        # "struct context" is a C object and does *not* take a reference
        # Therefore use a Python variable to keep the cdata object alive
        cdata = self._context.buf = jsonrpc_ffi.ffi.new('char[]', buf)
        self._context.buflen = len(buf)
        offset = self._context.offset = 0
        while offset != len(buf):
            error = jsonrpc_ffi.lib.split(self._context)
            if error and error != jsonrpc_ffi.lib.INCOMPLETE:
                self._error = protocols.errno.FRAMING_ERROR
                self._error_message = 'jsonrpc_ffi.split(): error {0}'.format(error)
                break
            nbytes = self._context.offset - offset
            if len(self._buffer) + nbytes > self.max_message_size:
                self._error = protocols.errno.MESSAGE_TOO_LARGE
                break
            if error == jsonrpc_ffi.lib.INCOMPLETE:
                self._buffer.extend(buf[offset:])
                offset = self._context.offset
                break
            chunk = buf[offset:self._context.offset]
            if self._buffer:
                self._buffer.extend(chunk)
                chunk = self._buffer
                self._buffer = bytearray()
            try:
                chunk = chunk.decode('utf8')
            except UnicodeDecodeError as e:
                self._error = protocols.errno.ENCODING_ERROR
                self._error_message = 'UTF-8 decoding error: {0!s}'.format(e)
                break
            try:
                message = json.loads(chunk)
            except ValueError as e:
                self._error = protocols.errno.PARSE_ERROR
                self._error_message = 'invalid JSON: {0!s}'.format(e)
                break
            if not check_message(message):
                self._error = protocols.errno.PARSE_ERROR
                self._error_message = 'invalid JSON-RPC message'
                break
            self._messages.append(message)
            offset = self._context.offset
        if self._error and offset == len(buf):
            offset = 0
        return offset


class JsonRpcBase(protocols.RequestResponseProtocol):
    """Base class for the JSON-RPC client and server implementations."""
    
    _exception = JsonRpcError
    default_version = '1.0'

    def __init__(self, message_handler=None, timeout=None):
        """The constructor takes the following arguments. The *message_handler*
        argument specifies an optional message handler. See the notes at the
        top for more information on the message handler.

        The optional *timeout* argument can be used to specify a timeout for
        the various network operations used.
        """
        super(JsonRpcBase, self).__init__(JsonRpcParser, timeout)
        self._message_handler = message_handler

    def _dispatch_fast_path(self, transport, message):
        if 'result' in message or 'error' in message:
            event = 'MethodResponse:{0}'.format(message['id'])
            if transport._events.emit(event, message):
                return True
        if not self._message_handler:
            transport._log.debug('no handler, dropping incoming message')
            return True
        return False

    def _dispatch_message(self, transport, message):
        assert self._message_handler is not None
        result = self._message_handler(message, self, transport)
        if result:
            self._send_message(transport, result)

    @switchpoint
    def _call_method(self, transport, method, *args):
        if transport is None or transport.closed:
            raise RuntimeError('not connected')
        message = create_request(method, args, version=self.default_version)
        self._send_message(transport, message)
        events = ('MethodResponse:{0}'.format(message['id']), 'HandleError')
        response = transport._events.wait(self._timeout, waitfor=events)
        if response == 'HandleError':
            raise self._transport._error
        event, response = response
        assert isinstance(response, dict)
        assert check_message(response)
        error = response.get('error')
        if error:
            raise JsonRpcError(protocols.errno.INVALID_REQUEST, error)
        return response.get('result')

    @switchpoint
    def _send_notification(self, transport, method, *args):
        if transport is None or transport.closed:
            raise RuntimeError('not connected')
        message = create_notification(method, args, version=self.default_version)
        self._send_message(transport, message)

    @switchpoint
    def _send_message(self, transport, message):
        if transport is None or transport.closed:
            raise RuntimeError('not connected')
        if not check_message(message):
            raise ValueError('illegal JSON-RPC message')
        self._log_response(message)
        serialized = json.dumps(message).encode('utf8')
        self._write(transport, serialized)


class JsonRpcClient(JsonRpcBase):
    """A JSON-RPC version 1 client."""

    @switchpoint
    @docfrom(JsonRpcBase._connect)
    def connect(self, address, ssl=False, local_address=None, **transport_args):
        self._connect(address, ssl, local_address, **transport_args)

    @switchpoint
    def call_method(self, method, *args):
        """Call a JSON-RPC method and wait for its response.

        The specified *method* is called with the given positional arguments.

        On success, the 'result' member of the JSON-RPC reply is returned, in
        the following way: if result is null or zero-length, None is returned.
        If result has length 1, then the first item is returned. If result
        contains more than 1 element, the list itself is returned.

        On error, an exception is raised with two arguments: the error code and
        an error message. In case the error is caused by the reception of a
        JSON-RPC error reply, the code will be ``INVALID_REQUEST`` and the
        error message will be the 'error' field from the error reply.
        """
        return self._call_method(self._transport, method, *args)

    @switchpoint
    def send_notification(self, notification, *args):
        """Send a JSON-RPC notification.

        The specified *notification* is called with the given positional
        arguments.
        """
        self._send_notification(self._transport, notification, *args)

    @switchpoint
    def send_message(self, message):
        """Send a raw JSON-RPC message.

        The message must be a dictionary that corresponds to the JSON-RPC
        specification.
        """
        self._send_message(self._transport, message)


class JsonRpcServer(JsonRpcBase):
    """A JSON-RPC version 1 server."""

    @property
    def clients(self):
        """A set containing the transports of the currently connected
        clients."""
        return self._clients

    @switchpoint
    @docfrom(JsonRpcBase._listen)
    def listen(self, address, ssl=False, **transport_args):
        self._listen(address, ssl, **transport_args)

    @switchpoint
    def call_method(self, client, method, *args):
        """Call a JSON-RPC method on a connected client.

        The *client* argument specifies the transport of the client to call the
        method on. It must be one of the transports in :attr:`clients`.

        For for information, see :meth:`JsonRpcClient.call_method`.
        """
        return self._call_method(client, method, *args)

    @switchpoint
    def send_notification(self, client, notification, *args):
        """Send a JSON-RPC notification to a connected client.

        The *client* argument specifies the transport of the client to send the
        message to. It must be one of the transports in :attr:`clients`.

        For for information, see :meth:`JsonRpcClient.send_notification`.
        """
        self._send_notification(client, notification, *args)

    @switchpoint
    def send_message(self, client, message):
        """Send a raw JSON-RPC message to a connected client.

        The *client* argument specifies the transport of the client to send the
        message to. It must be one of the transports in :attr:`clients`.

        For for information, see :meth:`JsonRpcClient.send_message`.
        """
        self._send_message(client, message)
