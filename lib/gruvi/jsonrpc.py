#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

"""
The :mod:`gruvi.jsonrpc` module implements a JSON-RPC client and server.

There are two version of JSON-RPC: version 1.0 and version 2.0. While these
versions are similar, they are not mutually compatible. The classes exposed by
this module implement both versions. The default version to use is stored in
:attr:`JsonRpcProtocol.default_version`, and most constructors take an argument
that can be used to override this.

The "batch" feature of version 2.0 is not supported. It more relevant for
JSON-RPC over HTTP rather for that clients and servers that operate directly on
top of a connection.

The two main classes in this module are :class:`JsonRpcClient` and
:class:`JsonRpcServer`. The difference is only who initiates the connection at
the transport level. The JSON-RPC protocol itself does not distinguish between
clients and servers.

Both the client and the server can receive and respond to incoming messages.
These may be method calls (more common for servers), or notifications (common
for both client and servers). These incoming messages are handled by a message
handler, which is mandatory for a server and optional for a client. Note that
for simple blocking method callls from client to a server no message handler is
needed.

Message handlers run in a separate dispatcher fiber, one per connection. This
means that a client will have at most one dispatcher fiber, while a server will
have exactly one fiber per connection. Because they run in a separate fiber,
message handlers can call into switchpoints themselves.
"""

from __future__ import absolute_import, print_function

import json
import functools
import six

from . import compat
from .hub import switchpoint, switch_back
from .util import delegate_method, Absent
from .transports import TransportError
from .protocols import ProtocolError, MessageProtocol
from .stream import Stream
from .endpoints import Client, Server
from .jsonrpc_ffi import lib, ffi

__all__ = ['JsonRpcError', 'JsonRpcVersion', 'JsonRpcProtocol',
           'JsonRpcClient', 'JsonRpcServer']

# Message types

REQUEST = 1   #: Constant indicating a JSON-RPC request message.
RESPONSE = 2  #: Constant indicating a JSON-RPC response message.

# JSON-RPC error codes. In both versions the "error" field is required to be an
# Object, but v2 specifies a structure for it. We use the v2 error format for
# both versions.

errorcode = {}  #: Dictionary mapping error codes to error names.
_errlist = {}
_errobjs = {}

def add_error(code, name, message):
    globals()[name] = code
    errorcode[code] = name
    _errlist[code] = message
    _errobjs[code] = {'code': code, 'message': message}

add_error(-32000, 'SERVER_ERROR', 'Server error')
add_error(-32001, 'MESSAGE_TOO_LARGE', 'Message too large')
add_error(-32002, 'UNKNOWN_RESPONSE', 'Unknown response')
add_error(-32600, 'INVALID_REQUEST', 'Invalid request')
add_error(-32601, 'METHOD_NOT_FOUND', 'Method not found')
add_error(-32602, 'INVALID_PARAMS', 'Invalid parameters')
add_error(-32603, 'INTERNAL_ERROR', 'Internal error')
add_error(-32700, 'PARSE_ERROR', 'Parse error')

del add_error

def strerror(code):
    """Return an error message for error *code*.

    The error code is the ``error.code`` field of a JSON-RPC response message.
    The JSON-RPC version 2 spec contains a list of standard error codes.
    """
    return _errlist.get(code, 'No error description available')


class JsonRpcError(ProtocolError):
    """Exception that is raised in case of JSON-RPC errors."""

    @property
    def error(self):
        """The ``error`` field from the JSON-RPC response, if available."""
        return self.args[1] if len(self.args) > 0 else None


# A class that encapsulates the differences between the two JSON-RPC versions
# that exist out there (1.0 and 2.0).

class JsonRpcVersion(object):
    """Class that encapsulates the differences between JSON-RPC vesion 1.0 and 2.0."""

    _id_template = 'gruvi.{}'

    def __init__(self, name):
        self._next_id = 0
        self._name = name

    @property
    def name(self):
        """Return the JSON-RPC version as a string, e.g. `'1.0'`."""
        return self._name

    def next_id(self):
        """Return a unique message ID."""
        msgid = self._id_template.format(self._next_id)
        self._next_id += 1
        return msgid

    @staticmethod
    def create(version):
        """Return a new instance for *version*, which can be either `'1.0'`
        or `'2.0'`."""
        clsname = 'JsonRpcV{}'.format(version.rstrip('.0'))
        cls = globals()[clsname]
        return cls(version)

    def check_message(self, message):
        """Check *message* and return the message type. Raise a `ValueError` in
        case of an invalid message."""
        raise NotImplementedError

    def create_request(self, method, args=None, notification=False):
        """Create a new request message for *method* with arguments *args*.

        The optional *notification* argument, if nonzero, creates a
        notification and no response to this message is expected.
        """
        raise NotImplementedError

    def create_response(self, request, result=None, error=None):
        """Create a new response message, as a response to *request*.

        A successful response is created when the optional *error* argument is
        not provided. In this case *result* specifies the result, which may be
        any value including ``None``. If *error* is provided, an error response
        is created, and *error* should be a dict as specified by the JSON-RPC
        specifications.

        The *request* argument may be explicitly set to ``None``, in which case
        this is an error response that is not specific to any one request.
        """
        raise NotImplementedError


class JsonRpcV1(JsonRpcVersion):
    """JSON-RPC version 1 message routines.

    See http://json-rpc.org/wiki/specification.
    """

    def check_message(self, message):
        msgid = message.get('id', Absent)
        if msgid is Absent:
            raise ValueError('"id" is absent')
        method = message.get('method', Absent)
        # If "method" is absent, it's a response. Otherwise it's a request.
        if method is Absent:
            result = message.get('result', Absent)
            error = message.get('error', Absent)
            if result is Absent or error is Absent or \
                    result is not None and error is not None or \
                    error is not None and not isinstance(error, dict) or \
                    len(message) != 3:
                raise ValueError('illegal "result" or "error" field')
            return RESPONSE
        elif isinstance(method, six.string_types):
            params = message.get('params', Absent)
            if not isinstance(params, (tuple, list)) or len(message) != 3:
                raise ValueError('illegal "param" field')
            return REQUEST
        else:
            raise ValueError('illegal "method" field')

    def create_request(self, method, args=None, notification=False):
        message = {'id': self.next_id() if not notification else None,
                   'method': method,
                   'params': [] if args is None else args}
        return message

    def create_response(self, request, result=None, error=None):
        message = {'id': request['id'] if request else None,
                   'result': result,
                   'error': error}
        return message


class JsonRpcV2(JsonRpcVersion):
    """JSON-RPC version 2 message routines.

    See http://www.jsonrpc.org/specification.
    """

    def check_message(self, message):
        version = message.get('jsonrpc')
        if version != '2.0':
            raise ValueError('illegal "version" field')
        msgid = message.get('id', Absent)
        if msgid is not Absent and msgid is not None and \
                    not isinstance(msgid, six.string_types) and \
                    not isinstance(msgid, (int, float)):
            raise ValueError('illegal "id" field')
        # If "method" is absent, it's a response. Otherwise it's a request.
        method = message.get('method', Absent)
        if method is Absent:
            result = message.get('result', Absent)
            error = message.get('error', Absent)
            if msgid is Absent or \
                    error is not Absent and not isinstance(error, dict) or \
                    (result is Absent) == (error is Absent) or \
                    len(message) != 3:
                raise ValueError('illegal "result" or "error" field')
            return RESPONSE
        elif isinstance(method, six.string_types):
            params = message.get('params', Absent)
            if params is not Absent and not isinstance(params, (dict, tuple, list)) or \
                    len(message) != 2 + (msgid is not Absent) + (params is not Absent):
                raise ValueError('illegal "param" field')
            return REQUEST
        else:
            raise ValueError('illegal "method" field')

    def create_request(self, method, args=None, notification=False):
        message = {'jsonrpc': '2.0',
                   'method': method,
                   'params': [] if args is None else args}
        if not notification:
            message['id'] = self.next_id()
        return message

    def create_response(self, request, result=None, error=None):
        message = {'jsonrpc': '2.0',
                   'id': request['id'] if request else None}
        if error is None:
            message['result'] = result
        else:
            message['error'] = error
        return message


def message_info(message):
    """Return a string describing a message, for debugging purposes."""
    method = message.get('method')
    msgid = message.get('id')
    error = message.get('error')
    if method and msgid is not None:
        return 'method call "{}", id = "{}"'.format(method, msgid)
    elif method:
        return 'notification "{}"'.format(method)
    elif error is not None and msgid is not None:
        return 'error reply to id = "{}"'.format(msgid)
    elif error is not None:
        code = error.get('code', '(none)')
        return 'error reply: {}'.format(errorcode.get(code, code))
    else:
        return 'method return for id = "{}"'.format(msgid)


def serialize(msg):
    """Serialize a JSON-RPC message."""
    return json.dumps(msg, indent=2).encode('utf-8')


# JSON-RPC protocol implementation.

class JsonRpcProtocol(MessageProtocol):
    """A JSON-RPC client and server :class:`~gruvi.Protocol` implementation."""

    #: Class level attribute that specifies the default timeout.
    default_timeout = 30

    #: Class level attribute that specifies the default JSON-RPC version.
    default_version = '2.0'

    # Any message larger than this and the connection is dropped.
    # This can be increased, but do note that message are kept in memory until
    # they are dispatched.
    max_message_size = 65536

    def __init__(self, handler=None, version=None, timeout=None):
        super(JsonRpcProtocol, self).__init__(handler, timeout=timeout)
        self._handler = handler
        self._version = self.default_version if version is None else version
        self._timeout = self.default_timeout if timeout is None else timeout
        self._buffer = bytearray()
        self._context = ffi.new('struct split_context *')
        self._method_calls = {}
        self._version = JsonRpcVersion.create(self._version)

    @property
    def version(self):
        """Return the :class:`JsonRpcVersion` instance for this protocol."""
        return self._version

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
        if self._error:
            self._log.debug('ignore data received after error')
            return
        offset = 0
        error = None
        # Set up the CFFI data structure to communicate with the splitter.
        # The "cdata" local variable keeps the data alive during this function.
        cdata = self._context.buf = ffi.from_buffer(data)
        self._context.buflen = len(data)
        self._context.offset = 0
        # Use the CFFI JSON splitter to delineate JSON messages in the input
        # stream. Then decode, parse, check and route them.
        while offset != len(data):
            split_error = lib.json_split(self._context)
            if split_error and split_error != lib.INCOMPLETE:
                self._log.debug('message split error: {}', split_error)
                error = PARSE_ERROR
                break
            # We have a good (partial) message. Check the size, including our buffer.
            size = len(self._buffer) + self._context.offset - offset
            if size > self.max_message_size:
                self._log.debug('message too large: {} bytes', size)
                error = MESSAGE_TOO_LARGE
                break
            # If we don't have a full message, save what we have and return.
            if split_error == lib.INCOMPLETE:
                assert self._context.offset == len(data)
                self._buffer.extend(data[offset:])
                break
            # A full message has been received. Process it.
            chunk = data[offset:self._context.offset]
            if self._buffer:
                # Prepend partial message from last parser invocation.
                self._buffer.extend(chunk)
                chunk = self._buffer
                self._buffer = bytearray()
            # Now parse it. Assume UTF-8 encoding. While the JSON spec allows
            # for UTF-16 and UTF-32, it makes it clear that those are not
            # interoperable (RFC7159, section 8.1).
            try:
                decoded = chunk.decode('utf8')
                message = json.loads(decoded)
            except Exception as e:
                self._log.debug('message parse error: {}', e)
                error = PARSE_ERROR
                break
            try:
                mtype = self._version.check_message(message)
            except ValueError as e:
                self._log.debug('illegal JSON-RPC message: {}', e)
                error = INVALID_REQUEST
                break
            self._log.debug(message_info(message))
            self._log.trace('\n\n{}\n', chunk)
            # Now route the message to its correct destination.
            if mtype == RESPONSE and message.get('id') in self._method_calls:
                # Response to a method call issued via call_method(): wake up caller
                switcher = self._method_calls.pop(message['id'])
                switcher(message)
            elif mtype == REQUEST and message.get('method') and not self._handler:
                # Method call but there is no handler: return error
                message = self._version.create_response(message, None, _errobjs[NO_SUCH_METHOD])
                self._transport.write(serialize(message))
            elif self._handler:
                # Everything else goes to the handler, if there is one.
                self._queue.put_nowait(message)
                self._maybe_pause_transport()
            offset = self._context.offset
        if error:
            message = self._version.create_response(None, None, _errobjs[error])
            self._transport.write(serialize(message))
            self._transport.close()
            self._error = JsonRpcError('Transport closed after protocol violation')

    @switchpoint
    def send_message(self, message):
        """Send a raw JSON-RPC message.

        The *message* argument must be a dictionary containing a valid JSON-RPC
        message according to the version passed into the constructor.
        """
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._transport is None:
            raise JsonRpcError('not connected')
        self._version.check_message(message)
        self._writer.write(serialize(message))

    @switchpoint
    def call_method(self, method, *args):
        """Call a JSON-RPC method and wait for its result.

        The *method* is called with positional arguments *args*.

        On success, the ``result`` field from the JSON-RPC response is
        returned.  On error, a :class:`JsonRpcError` is raised, which you can
        use to access the ``error`` field of the JSON-RPC response.
        """
        message = self._version.create_request(method, args)
        msgid = message['id']
        try:
            with switch_back(self._timeout) as switcher:
                self._method_calls[msgid] = switcher
                self.send_message(message)
                args, _ = self._hub.switch()
        finally:
            self._method_calls.pop(msgid, None)
        response = args[0]
        assert response['id'] == msgid
        error = response.get('error')
        if error is not None:
            raise JsonRpcError('error response calling "{}"'.format(method), error)
        return response['result']

    @switchpoint
    def send_notification(self, method, *args):
        """Send a JSON-RPC notification.

        The notification *method* is sent with positional arguments *args*.
        """
        message = self._version.create_request(method, args, notification=True)
        self.send_message(message)

    @switchpoint
    def send_response(self, request, result=None, error=None):
        """Respond to a JSON-RPC method call.

        This is a response to the message in *request*. If *error* is not
        provided, then this is a succesful response, and the value in *result*,
        which may be ``None``, is passed back to the client. if *error* is
        provided and not ``None`` then an error is sent back. In this case
        *error* must be a dictionary as specified by the JSON-RPC spec.
        """
        message = self._version.create_response(request, result, error)
        self.send_message(message)


class JsonRpcClient(Client):
    """A JSON-RPC :class:`~gruvi.Client`."""

    def __init__(self, handler=None, version=None, timeout=None):
        """
        The *handler* argument specifies an optional JSON-RPC message handler.
        You need to supply a message handler if you want to listen to
        notifications or you want to respond to server-to-client method calls.
        If provided, the message handler it must be a callable with signature
        ``handler(message, transport, protocol)``.

        The *version* and *timeout* argument can be used to override the
        default protocol version and timeout, respectively.
        """
        protocol_factory = functools.partial(JsonRpcProtocol, handler, version)
        super(JsonRpcClient, self).__init__(protocol_factory, timeout)

    protocol = Client.protocol

    delegate_method(protocol, JsonRpcProtocol.send_message)
    delegate_method(protocol, JsonRpcProtocol.call_method)
    delegate_method(protocol, JsonRpcProtocol.send_notification)


class JsonRpcServer(Server):
    """A JSON-RPC :class:`~gruvi.Server`."""

    max_connections = 1000

    def __init__(self, handler, version=None, timeout=None):
        """
        The *handler* argument specifies the JSON-RPC message handler. It must
        be a callable with signature ``handler(message, transport, protocol)``.
        The message handler is called in a separate dispatcher fiber (one per
        connection).

        The *version* and *timeout* argument can be used to override the
        default protocol version and timeout, respectively.
        """
        protocol_factory = functools.partial(JsonRpcProtocol, handler, version)
        super(JsonRpcServer, self).__init__(protocol_factory, timeout=timeout)
