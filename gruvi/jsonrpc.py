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
from .protocols import errno, ParseError

__all__ = ['check_message', 'create_response', 'create_error',
           'JsonRpcError', 'JsonRpcClient', 'JsonRpcServer']


class JsonRpcError(error.Error):
    """Exception that is raised in case of JSON-RPC protocol errors."""


_allowed_message_keys = frozenset(('jsonrpc', 'id', 'method', 'params',
                                   'result', 'error'))

def check_message(message):
    """Validate a JSON-RPC message.
    
    The message must be a dictionary. Return True if the message is valid,
    False otherwise.
    """
    if not isinstance(message, dict):
        return False
    if 'id' not in message:
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
        if message['id'] is None:
            return False
        if 'result' not in message and 'error' not in message or \
                    message.get('result') is not None and \
                        message.get('error') is not None:
            return False
        if 'params' in message:
            return False
    if set(message) - _allowed_message_keys:
        return False
    return True


def create_response(message, result):
    """Create a JSON-RPC response message."""
    msg = { 'id': message['id'], 'result': result, 'jsonrpc': '2.0' }
    return msg

def create_error(message, error):
    """Create a JSON-RPC error response message."""
    msg = { 'id': message['id'], 'error': error, 'jsonrpc': '2.0' }
    return msg

def create_notification(method, *args):
    """Create a JSON-RPC notification message."""
    msg = { 'id': None, 'method': method, 'params': args, 'jsonrpc': '2.0' }
    return msg


class JsonRpcParser(protocols.Parser):
    """A JSON-RPC Parser."""

    max_message_size = 128*1024

    def __init__(self):
        super(JsonRpcParser, self).__init__()
        self._buffer = bytearray()
        self._context = jsonrpc_ffi.ffi.new('struct context *')

    def is_partial(self):
        return len(self._buffer) > 0

    def feed(self, buf):
        # "struct context" is a C object and does *not* take a reference
        # Therefore use a Python variable to keep the cdata object alive
        cdata = self._context.buf = jsonrpc_ffi.ffi.new('char[]', buf)
        self._context.buflen = len(buf)
        offset = self._context.offset = 0
        while offset != len(buf):
            error = jsonrpc_ffi.lib.split(self._context)
            if error and error != jsonrpc_ffi.lib.INCOMPLETE:
                raise ParseError(errno.FRAMING_ERROR, 'framing error {0}'.format(error))
            nbytes = self._context.offset - offset
            if len(self._buffer) + nbytes > self.max_message_size:
                raise ParseError(errno.MESSAGE_TOO_LARGE, 'message exceeds maximum size')
            if error == jsonrpc_ffi.lib.INCOMPLETE:
                self._buffer.extend(buf[offset:])
                return
            chunk = buf[offset:self._context.offset]
            if self._buffer:
                self._buffer.extend(chunk)
                chunk = self._buffer
                self._buffer = bytearray()
            try:
                chunk = chunk.decode('utf8')
            except UnicodeDecodeError as e:
                raise ParseError(errno.PARSE_ERROR, 'encoding error: {0!s}'.format(str(e)))
            try:
                message = json.loads(chunk)
            except ValueError as e:
                raise ParseError(errno.PARSE_ERROR, 'invalid JSON: {0!s}'.format(e))
            if not check_message(message):
                print(message)
                raise ParseError(errno.PARSE_ERROR, 'invalid JSON-RPC message')
            self._messages.append(message)
            offset = self._context.offset


class JsonRpcBase(protocols.RequestResponseProtocol):
    """Base class for the JSON-RPC client and server implementations."""
    
    _exception = JsonRpcError

    def __init__(self, message_handler=None, timeout=None, _trace=False):
        """The constructor takes the following arguments. The *message_handler*
        argument specifies an optional message handler. See the notes at the
        top for more information on the message handler.

        The optional *timeout* argument can be used to specify a timeout for
        the various network operations used.
        """
        super(JsonRpcBase, self).__init__(JsonRpcParser, timeout)
        self._message_handler = message_handler
        self._trace = _trace

    def _init_transport(self, transport):
        super(JsonRpcBase, self)._init_transport(transport)
        transport._next_message_id = 1

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
        message = { 'id': 'gruvi.{0}'.format(transport._next_message_id),
                    'method': method, 'params': args, 'jsonrpc': '2.0' }
        transport._next_message_id += 1
        self._send_message(transport, message)
        events = ('MethodResponse:{0}'.format(message['id']), 'HandleError')
        try:
            event, response = transport._events.wait(self._timeout, waitfor=events)
        except Timeout:
            raise JsonRpcError(PROTO_TIMEOUT, 'timeout waiting for reply')
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, dict)
        assert check_message(response)
        error = response.get('error')
        if error:
            raise JsonRpcError(errno.INVALID_REQUEST, error)
        return response.get('result')

    @switchpoint
    def _send_notification(self, transport, method, *args):
        if transport is None or transport.closed:
            raise RuntimeError('not connected')
        message = create_notification(method, *args)
        self._send_message(transport, message)

    @switchpoint
    def _send_message(self, transport, message):
        if transport is None or transport.closed:
            raise RuntimeError('not connected')
        if not check_message(message):
            raise ValueError('illegal JSON-RPC message')
        serialized = json.dumps(message, ensure_ascii=True).encode('ascii')
        self._write(transport, serialized)
        self._log_response(message)

    def _log_request(self, message):
        if self._trace:
            self._log.debug('Incoming message: {!s}', message)

    def _log_response(self, message):
        if self._trace:
            self._log.debug('Outgoing message: {!s}', message)


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
