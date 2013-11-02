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

from . import hub, error, logging, compat
from .hub import switchpoint
from .fiber import ConditionSet, Queue, Fiber
from .pyuv import pyuv_exc, TCP, Pipe
from .ssl import SSL
from .util import objref, saddr, getaddrinfo, create_connection, docfrom

__all__ = ['errno', 'ProtocolError', 'Protocol']


class errno(object):
    """Errno values for ProtocolError."""
    OK = 0
    TIMEOUT = 1
    PARSE_ERROR = 2
    SERVER_BUSY = 3
    SERVER_ERROR = 4
    HANDLER_ERROR = 5
    AUTH_ERROR = 6
    INVALID_REQUEST = 7
    MESSAGE_TOO_LARGE = 8
    FRAMING_ERROR = 9
    PARSE_ERROR = 10


class ProtocolError(error.Error):
    """Protocol error."""


class Protocol(object):
    """Abstract base class for protocols."""

    _exception = ProtocolError

    max_connections = 1000
    max_buffer_size = 256*1024

    def __init__(self, timeout=None):
        self._timeout = timeout
        self._transport = None
        self._hub = hub.get_hub()
        self._logger = logging.get_logger(objref(self))
        self._clients = set()
        self._client_factory = None

    @property
    def timeout(self):
        """Timeout for network operations."""
        return self._timeout

    @property
    def transport(self):
        """The underlying transport."""
        return self._transport

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
            self._logger.debug('listen(): bound to {0}'.format(saddr(address)))
            self._local_address = (address, '')
            self._client_factory = Pipe
        elif isinstance(address, tuple):
            transport = TCP() # even for SSL the listening socket is TCP
            result = getaddrinfo(address[0], address[1], socket.AF_UNSPEC,
                                 socket.SOCK_STREAM, socket.IPPROTO_TCP)
            if len(result) > 1:
                self._logger.warning('listen(): multiple addresses, '
                                     'taking first one')
            address = result[0][4]
            transport.bind(address)
            self._logger.debug('listen(): bound to {0}'.format(saddr(address)))
            self._local_address = address
            client_type = SSL if ssl else TCP
            if ssl:
                transport_args['server_side'] = True
            self._client_factory = lambda: client_type(**transport_args)
        elif hasattr(address, 'listen'):
            transport = address
            if hasattr(transport, 'getsockname'):
                self._local_address = transport.getsockname()
            else:
                self._local_address = ('<unknown address>', 0)
            self._client_factory = type(transport)
        else:
            raise TypeError('expecting a string, a tuple or a transport')
        self._transport = transport
        self._transport.listen(self._on_new_connection)
        self._logger.debug('listen(): transport is {0}'
                                .format(objref(transport)))

    def _on_new_connection(self, transport, error):
        """Callback that is called for new connections."""
        assert transport is self._transport
        if error:
            self._logger.error('error {0} in listen callback'.format(error))
            return
        client = self._client_factory()
        self._clients.add(client)
        transport.accept(client)
        if len(self._clients) >= self.max_connections:
            self._logger.error('max connections reached, dropping connection')
            self._close_transport(client, errno.SERVER_BUSY)
            return
        self._logger.debug('new client on {0}'.format(objref(client)))
        self._init_transport(client)

    def _init_transport(self, transport):
        """Initialize a client or server transport."""
        transport._eof = False
        transport._error = None
        transport._events = ConditionSet()
        transport._write_buffer = 0
        transport._logger = logging.get_logger(objref(self))
        transport.start_read(self._on_transport_readable)

    def _close_transport(self, transport, error=None):
        """Close a client or server transport."""
        def on_transport_closed(transport):
            if transport in self._clients:
                self._clients.remove(transport)
            # _init_transport() has not been called if the transport is closed in
            # _on_new_connection()
            if error and hasattr(transport, '_events'):
                transport._error = error
                transport._events.notify('HandleError')
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
                transport._events.notify('HandleError')
                return
            oldsize = transport._write_buffer
            transport._write_buffer -= nbytes
            if transport._write_buffer < self.max_buffer_size <= oldsize:
                transport._events.notify('BufferBelowThreshold')
            if transport._write_buffer == 0:
                transport._events.notify('BufferEmpty')
        transport._write_buffer += nbytes
        transport.write(data, on_write_complete)
        if transport._write_buffer > self.max_buffer_size:
            transport._events.wait('BufferBelowThreshold', 'HandleError')
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
            transport._events.wait('BufferEmpty', 'HandleError')
        if transport._error:
            raise transport._error

    @switchpoint
    def _shutdown(self, transport):
        """Close the transport in the write direction."""
        transport.shutdown(self._hub.switch_back())
        self._hub.switch(self.timeout)

    @switchpoint
    @docfrom(create_connection)
    def _connect(self, address, ssl=False, local_address=None,
                 **transport_args):
        if self._transport is not None and not self._transport.closed:
            raise RuntimeError('already connected')
        transport = create_connection(address, ssl, local_address,
                                      **transport_args)
        self._transport = transport
        self._logger.debug('connect(): transport is {0}'
                                .format(objref(transport)))
        self._init_transport(self._transport)

    @switchpoint
    def close(self):
        """Close the underlying transport. """
        if self._clients:
            def on_client_close(transport):
                self._clients.remove(transport)
                if not self._clients:
                    switch_back()
            for client in self._clients:
                if not client.closed:
                    client.close(on_client_close)
            switch_back = self._hub.switch_back()
            self._hub.switch(self._timeout)
        if not self._transport.closed:
            self._transport.close(self._hub.switch_back())
            self._hub.switch(self._timeout)

    _close = close  # XXX: migration aid


class ParseError(ProtocolError):
    """Raised by parser.feed()."""


class Parser(object):
    """Abstract base class for request/response parsers."""

    def __init__(self):
        self._messages = collections.deque()

    def feed(self, buf):
        raise NotImplementedError

    def pop_message(self):
        if self._messages:
            return self._messages.popleft()

    def is_partial(self):
        raise NotImplementedError


class RequestResponseProtocol(Protocol):
    """Abstract base class for request/response protocols."""

    def __init__(self, parser_factory, timeout=None):
        """Create a new protocol endpoint."""
        super(RequestResponseProtocol, self).__init__(timeout)
        self._parser_factory = parser_factory

    def _init_transport(self, transport):
        """Initialize a client or server transport."""
        super(RequestResponseProtocol, self)._init_transport(transport)
        transport._parser = self._parser_factory()
        def on_queue_size_change(oldsize, newsize):
            if self.max_buffer_size is None:
                return
            if oldsize < self.max_buffer_size <= newsize:
                transport.stop_read()
            elif oldsize >= self.max_buffer_size > newsize:
                transport.start_read(self._on_transport_readable)
        transport._queue = Queue(on_queue_size_change)
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
            # This can be a half-close so continue processing the queue
            transport._eof = True
            if transport._parser.is_partial():
                transport._logger.error('parse error: partial message')
                error = self._exception(errno.PARSE_ERROR, 'partial message')
            else:
                transport._logger.debug('got EOF')
                error = None
        elif error:
            # Close immediately here, do not try to process the queue if any.
            transport._logger.error('error {0} in read callback'.format(error))
            self._close_transport(transport, pyuv_exc(transport, error))
            return
        else:
            try:
                transport._parser.feed(data)
            except ParseError as e:
                transport._logger.error('parse error: {0!s}'.format(e))
                error = self._exception(errno.PARSE_ERROR, str(e))
        # Dispatch either to the fast path or to the slow path via the queue
        # and the dispatcher (which runs in a separate fiber).
        while True:
            message = transport._parser.pop_message()
            if message is None:
                break
            if self._dispatch_fast_path(transport, message):
                continue
            if transport._dispatcher is None:
                self._start_dispatcher(transport)
            transport._queue.put(message)
        # Do we need to close the connection?
        if transport._eof or error:
            if not transport._dispatcher or transport._queue.qsize() == 0:
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
                transport._logger.exception('exception in handler')
                error = self._exception(errno.HANDLER_ERROR, str(e))
                self._close_transport(transport, error)
                break
        transport._logger.debug('dispatcher exiting')

    def _dispatch_message(self, transport, message):
        """Slow path dispatch. This is run in the dispatcher fiber."""
        raise NotImplementedError
