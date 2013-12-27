#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import json
import socket
import collections
import pyuv

from . import hub, error, logging, compat, util
from .hub import switchpoint, switch_back
from .fibers import Fiber
from .sync import Signal, Queue
from .pyuv import pyuv_exc, TCP, Pipe
from .ssl import SSL
from .util import docfrom, objref

__all__ = ['errno', 'ProtocolError', 'Protocol']


class errno(object):
    """Errno values for ProtocolError."""

    OK = 0
    TIMEOUT = 1
    SERVER_BUSY = 2
    SERVER_ERROR = 3
    FRAMING_ERROR = 4
    MESSAGE_TOO_LARGE = 5
    ENCODING_ERROR = 6
    PARSE_ERROR = 7
    INVALID_REQUEST = 8
    HANDLER_ERROR = 9
    AUTHENTICATION_ERROR = 10

    errlist = {
        OK: 'No error',
        TIMEOUT: 'A timeout occurred',
        SERVER_BUSY: 'The server is currently busy',
        SERVER_ERROR: 'Internal server error',
        FRAMING_ERROR: 'Framing error',
        MESSAGE_TOO_LARGE: 'Message is too large',
        ENCODING_ERROR: 'Character encoding error',
        PARSE_ERROR: 'Parse error',
        INVALID_REQUEST: 'Invalid request',
        HANDLER_ERROR: 'Request handler error',
        AUTHENTICATION_ERROR: 'Authentication failed'
    }

    errorcode = dict((k,v) for k,v in locals().items() if k.isupper())

    @classmethod
    def strerror(cls, code):
        return cls.errlist.get(code, 'Unknown error')


class ProtocolError(error.Error):
    """Protocol error."""

    def __init__(self, code, message=None):
        if message is None:
            message = errno.strerror(errno)
        super(ProtocolError, self).__init__(code, message)

    def __str__(self):
        errname = errno.errorcode.get(self.args[0], 'UNKNOWN')
        return '{0} ({1}) ({2})'.format(self.args[0], errname, self.args[1])


class Protocol(object):
    """Abstract base class for protocols."""

    _exception = ProtocolError

    max_connections = 1000
    max_buffer_size = 256*1024

    def __init__(self, timeout=None):
        self._timeout = timeout
        self._transport = None
        self._hub = hub.get_hub()
        self._log = logging.get_logger(self)
        self._clients = set()
        self._client_factory = None
        self._client_disconnected = Signal()

    @property
    def timeout(self):
        """Timeout for network operations."""
        return self._timeout

    @property
    def transport(self):
        """The underlying transport."""
        return self._transport

    @property
    def client_disconnected(self):
        """Signal raised when a client disconnected."""
        return self._client_disconnected

    def _listen(self, address, ssl=False, **transport_args):
        """Start listening for new connections on *address*.

        The *address* may be either be a string, a (host, port) tuple, or a
        transport. If it is a string, this method creates a new ``pyuv.Pipe``
        instance, binds it to *address* and will start listening for new
        connections on it.

        If the address is a tuple, this method creates a new ``pyuv.TCP`` or
        ``ssl.SSL`` transport, depending on the value of *ssl*. The host and
        port elements of the tuple may be DNS and service names, and will be
        resolved resolved using :func:`gruvi.util.getaddrinfo()`. After this
        the transport is bound to the resolved address and this method will
        start listening for new connections on it.

        Extra keyword arguments may be provided in *transport_args*. These will
        be passed to the constructor of the transport that is being used for
        client connections. This is useful when using SSL.

        Finally, *address* may be a transport that was already bound to a local
        address. In this case, all other arguments are ignored.
        """
        if self._transport is not None and not self._transport.closed:
            raise RuntimeError('already listening')
        if isinstance(address, (compat.binary_type, compat.text_type)):
            transport = Pipe()
            transport.bind(address)
            self._log.debug('bound to {}', util.saddr(address))
            self._client_factory = Pipe
        elif isinstance(address, tuple):
            transport = TCP() # even for SSL the listening socket is TCP
            result = util.getaddrinfo(address[0], address[1], socket.AF_UNSPEC,
                                      socket.SOCK_STREAM, socket.IPPROTO_TCP)
            resolved = result[0][4]
            if len(result) > 1:
                self._log.warning('multiple addresses for {}, using {}',
                                  util.saddr(address), util.saddr(resolved))
            transport.bind(resolved)
            self._log.debug('bound to {}', util.saddr(resolved))
            client_type = SSL if ssl else TCP
            if ssl:
                transport_args['server_side'] = True
            self._client_factory = lambda: client_type(**transport_args)
        elif hasattr(address, 'listen'):
            transport = address
            self._client_factory = type(transport)
        else:
            raise TypeError('expecting a string, a tuple or a transport')
        self._transport = transport
        self._transport.listen(self._on_new_connection)
        self._log.debug('transport is {}', objref(transport))

    def _on_new_connection(self, transport, error):
        """Callback that is called for new connections."""
        assert transport is self._transport
        if error:
            self._log.error('error {} in listen callback', error)
            return
        client = self._client_factory()
        self._clients.add(client)
        transport.accept(client)
        if len(self._clients) >= self.max_connections:
            self._log.error('max connections reached, dropping connection')
            self._close_transport(client, errno.SERVER_BUSY)
            return
        self._log.debug('new client on {}', objref(client))
        self._init_transport(client)

    def _init_transport(self, transport):
        """Initialize a client or server transport."""
        transport._eof = False
        transport._error = None
        transport._events = Signal()
        transport._write_buffer = 0
        transport._log = logging.get_logger(self)
        transport.start_read(self._on_transport_readable)

    def _close_transport(self, transport, error=None):
        """Close a client or server transport."""
        def on_transport_closed(transport):
            if transport in self._clients:
                self._clients.remove(transport)
                self.client_disconnected.emit(self)
            # _init_transport() has not been called if the transport is closed in
            # _on_new_connection()
            if error and hasattr(transport, '_events'):
                transport._error = error
                transport._events.emit('HandleError')
        transport.close(on_transport_closed)

    def _on_transport_readable(self, transport, data, error):
        raise NotImplementedError

    @switchpoint
    def _write(self, transport, data):
        """Write *data* to the transport."""
        if not data:
            return 0
        if transport._error:
            raise transport._error
        nbytes = len(data)
        def on_write_complete(transport, error):
            if error:
                error = pyuv_exc(transport, error)
                transport._error = error
                transport._events.emit('HandleError')
                return
            oldsize = transport._write_buffer
            transport._write_buffer -= nbytes
            if transport._write_buffer < self.max_buffer_size <= oldsize:
                transport._events.emit('BufferBelowThreshold')
            if transport._write_buffer == 0:
                transport._events.emit('BufferEmpty')
        transport._write_buffer += nbytes
        transport.write(data, on_write_complete)
        if transport._write_buffer > self.max_buffer_size:
            events = ('BufferBelowThreshold', 'HandleError')
            transport._events.wait(waitfor=events)
        if transport._error:
            raise transport._error
        return nbytes

    @switchpoint
    def _writelines(self, transport, lines):
        """Write the elements of the sequence *lines* to the transport."""
        for line in lines:
            self._write(transport, line)

    @switchpoint
    def _flush(self, transport):
        """Wait until all data is written to the transport."""
        if not transport._write_buffer:
            return
        if not transport._error:
            transport._events.wait(waitfor=('BufferEmpty', 'HandleError'))
        if transport._error:
            raise transport._error

    @switchpoint
    def _shutdown(self, transport):
        """Close the transport in the write direction."""
        with switch_back(self.timeout) as switcher:
            transport.shutdown(switcher)
            self._hub.switch()

    @switchpoint
    @docfrom(util.create_connection)
    def _connect(self, address, ssl=False, local_address=None, **transport_args):
        if self._transport is not None and not self._transport.closed:
            raise RuntimeError('already connected')
        self._log.debug('connect to {}', util.saddr(address))
        transport = util.create_connection(address, ssl, local_address, **transport_args)
        self._transport = transport
        self._log.debug('transport is {}', objref(transport))
        self._init_transport(self._transport)

    @switchpoint
    def close(self):
        """Close the underlying transport. """
        with switch_back(self.timeout) as switcher:
            if self._clients:
                def on_client_close(transport):
                    self._clients.remove(transport)
                    if not self._clients:
                        switcher()
                for client in self._clients:
                    if not client.closed:
                        client.close(on_client_close)
                self._hub.switch()
            if not self._transport.closed:
                self._transport.close(switcher)
                self._hub.switch()


class Parser(object):
    """Abstract base class for request/response parsers."""

    def __init__(self):
        self._messages = collections.deque()
        self._error = None
        self._error_message = None

    @property
    def error(self):
        return self._error

    @property
    def error_message(self):
        return self._error_message

    def feed(self, buf):
        raise NotImplementedError

    def pop_message(self):
        if self._messages:
            return self._messages.popleft()


class RequestResponseProtocol(Protocol):
    """Abstract base class for request/response protocols.

    Messages are parsed from the transport using a parser. Parsed messages are
    then either dispatched by :meth:`_dispatch_fast_path`, or put in a queue to
    be handled asynchronously by :meth:`_dispatch_message`.
    """

    def __init__(self, parser_factory, timeout=None):
        """Create a new protocol endpoint."""
        super(RequestResponseProtocol, self).__init__(timeout)
        self._parser_factory = parser_factory

    def _init_transport(self, transport):
        """Initialize a client or server transport."""
        super(RequestResponseProtocol, self)._init_transport(transport)
        transport._parser = self._parser_factory()
        transport._queue = Queue()
        def on_queue_size_change(oldsize, newsize):
            if self.max_buffer_size is None:
                return
            if oldsize < self.max_buffer_size <= newsize:
                transport.stop_read()
            elif oldsize >= self.max_buffer_size > newsize:
                transport.start_read(self._on_transport_readable)
        transport._queue.size_changed.connect(on_queue_size_change)
        transport._dispatcher = None

    def _start_dispatcher(self, transport):
        transport._dispatcher = Fiber(self._dispatch, args=(transport,))
        transport._dispatcher.start()

    def _dispatch_fast_path(self, transport, message):
        """Fast path dispatch. This is run in the read callback."""
        return False

    def _on_transport_readable(self, transport, data, error):
        """Callback that is called when a transport has data available."""
        if error == pyuv.errno.UV_EOF:
            transport._eof = True
            error = None
            data = b''  # feed empty string into parser to mark EOF
        elif error:
            # Close immediately here, do not try to process the queue if any.
            transport._log.error('error {} in read callback', error)
            self._close_transport(transport, pyuv_exc(transport, error))
            return
        nbytes = transport._parser.feed(data)
        if nbytes != len(data):
            error = self._exception(transport._parser.error,
                                    transport._parser.error_message)
            transport._log.error('protocol error: {!s}', error)
        # Dispatch either to the fast path or to the slow path via the queue
        # and the dispatcher (which runs in a separate fiber).
        while True:
            message = transport._parser.pop_message()
            if message is None:
                break
            self._log_request(message)
            if self._dispatch_fast_path(transport, message):
                continue
            if transport._dispatcher is None:
                self._start_dispatcher(transport)
            transport._queue.put(message)
        # Do we need to close the connection?
        if transport._eof or error:
            if not transport._dispatcher or not transport._queue:
                # Close the connection right away
                self._close_transport(transport, error)
            else:
                # Let the dispatcher transport the error and close the connection
                transport._queue.put(error)

    def _dispatch(self, transport):
        """Dispatch messages for a client or server. This method runs in its
        own fiber."""
        while True:
            message = transport._queue.get()
            if not message:
                self._close_transport(transport)  # EOF
                break
            elif isinstance(message, Exception):
                self._close_transport(transport, message)
                break
            try:
                self._dispatch_message(transport, message)
            except Exception as e:
                transport._log.exception('exception in handler')
                error = self._exception(errno.HANDLER_ERROR, str(e))
                self._close_transport(transport, error)
                break
        transport._log.debug('dispatcher exiting')

    def _dispatch_message(self, transport, message):
        """Slow path dispatch. This is run in the dispatcher fiber."""
        raise NotImplementedError

    def _log_request(self, message):
        """Log a request. To be implemented in a subclass."""

    def _log_response(self, message):
        """Log a response. To be implemented in a subclass."""
