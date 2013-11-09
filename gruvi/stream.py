#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

"""
A stream protocol client and server.

The stream protocol doesn't really do any protocol handling. It is simply a
raw, byte oriented connection. You can think of it as a blocking interface on
top of a transport.
"""

from __future__ import absolute_import, print_function

import io
import pyuv

from .hub import switchpoint
from .pyuv import pyuv_exc
from .util import docfrom, objref
from . import fibers, reader, protocols, error


__all__ = ['StreamError', 'Stream', 'StreamClient', 'StreamServer']


class StreamError(error.Error):
    """Exception that is raised in case of stream protocol errors."""


class Stream(io.BufferedIOBase):
    """A byte stream."""

    def __init__(self, transport, protocol):
        self._transport = transport
        self._protocol = protocol

    @switchpoint
    @docfrom(reader.Reader.read)
    def read(self, size=None):
        return self._transport._reader.read(size)

    @switchpoint
    @docfrom(reader.Reader.readline)
    def readline(self, limit=-1):
        return self._transport._reader.readline(limit)

    @switchpoint
    @docfrom(reader.Reader.readlines)
    def readlines(self, hint=-1):
        return self._transport._reader.readlines(hint)

    @switchpoint
    @docfrom(protocols.Protocol._write)
    def write(self, data):
        return self._protocol._write(self._transport, data)

    @switchpoint
    @docfrom(protocols.Protocol._writelines)
    def writelines(self, lines):
        self._protocol._writelines(self._transport, lines)

    @switchpoint
    @docfrom(protocols.Protocol._flush)
    def flush(self):
        self._protocol._flush(self._transport)

    @switchpoint
    @docfrom(protocols.Protocol._shutdown)
    def shutdown(self):
        self._protocol._shutdown(self._transport)


class StreamBase(protocols.Protocol):

    _exception = StreamError

    def __init__(self, timeout=None):
        """The optional *timeout* argument can be used to specify a timeout for
        network operations."""
        super(StreamBase, self).__init__(timeout)
        self._connection_handler = None

    def _init_transport(self, transport):
        super(StreamBase, self)._init_transport(transport)
        def on_size_change(oldsize, newsize):
            if self.max_buffer_size is None:
                return
            if oldsize < self.max_buffer_size <= newsize:
                transport.stop_read()
            elif newsize < self.max_buffer_size <= oldsize:
                transport.start_read(self._on_transport_readable)
        transport._buffers = reader.BufferList()
        transport._buffers.size_changed.connect(on_size_change)
        transport._reader = reader.Reader(transport._buffers)
        transport._stream = Stream(transport, self)
        if self._connection_handler is None:
            return
        transport._dispatcher = fibers.Fiber(self._dispatch_connection,
                                             args=(transport,))
        transport._dispatcher.start()

    def _on_transport_readable(self, transport, data, error):
        if error == pyuv.errno.UV_EOF:
            transport._eof = True
            transport._buffers.feed_eof()
        elif error:
            transport._error = pyuv_exc(transport, error)
            self._close_transport(transport)
        else:
            transport._buffers.feed(data)

    def _dispatch_connection(self, transport):
        try:
            self._connection_handler(transport._stream, self, transport)
        except Exception as e:
            transport._log.exception('exception in handler')
            error = self._exception(protocols.errno.HANDLER_ERROR, str(e))
        else:
            error = None
        self._close_transport(transport, error)


class StreamClient(StreamBase):
    """A stream protocol client."""

    @switchpoint
    @docfrom(StreamBase._connect)
    def connect(self, address, ssl=False, local_address=None,
                **transport_args):
        self._connect(address, ssl, local_address, **transport_args)

    @switchpoint
    @docfrom(Stream.read)
    def read(self, size=None):
        return self.transport._stream.read(size)

    @switchpoint
    @docfrom(Stream.readline)
    def readline(self, limit=-1):
        return self.transport._stream.readline(limit)

    @switchpoint
    @docfrom(Stream.readlines)
    def readlines(self, hint=-1):
        return self.transport._stream.readlines(hint)

    @switchpoint
    @docfrom(Stream.write)
    def write(self, data):
        return self.transport._stream.write(data)

    @switchpoint
    @docfrom(Stream.writelines)
    def writelines(self, lines):
        self.transport._stream.writelines(lines)

    @switchpoint
    @docfrom(Stream.flush)
    def flush(self):
        self.transport._stream.flush()

    @switchpoint
    @docfrom(Stream.shutdown)
    def shutdown(self):
        self.transport._stream.shutdown()


class StreamServer(StreamBase):
    """A stream protocol server."""

    def __init__(self, connection_handler, timeout=None):
        """The constructor accepts the following arguments. The
        *connection_handler* specifies a connection handler.The signature of
        the connection handler is ``connection_handler(stream, protocol,
        client)``. Here, *stream* is an object that implements the
        :class:`io.BufferedIOBase` interface.  The *protocol* is the server
        instance, and *client* is the transport of the client.

        The connection handler can use the methods on *stream* to interact with
        the client. If the connection handler exits, the connection is closed.

        The optional *timeout* argument can be used to specify a timeout for
        network operations.
        """
        super(StreamServer, self).__init__(timeout)
        self._connection_handler = connection_handler

    @property
    def clients(self):
        """A set containing the transports of the currently connected
        clients."""
        return self._clients

    @switchpoint
    @docfrom(StreamBase._listen)
    def listen(self, address, ssl=False, **transport_args):
        self._listen(address, ssl, **transport_args)
