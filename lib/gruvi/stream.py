#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from io import BufferedIOBase

from . import compat
from .util import delegate_method
from .sync import Event
from .errors import Error, Timeout, Cancelled
from .protocols import Protocol, ProtocolError
from .endpoints import Client, Server
from .hub import switchpoint
from .fibers import spawn

__all__ = ['StreamError', 'StreamBuffer', 'Stream', 'StreamProtocol',
           'StreamClient', 'StreamServer']


class StreamError(Error):
    """Stream error."""


class StreamBuffer(object):
    """A stream buffer.

    This is a utility class that is used to by :class:`Stream` to implement the
    read side buffering.
    """

    default_buffer_size = 65536

    def __init__(self, transport=None, timeout=None):
        self._transport = transport
        self._timeout = timeout
        self._can_read = Event()
        self._buffers = []
        self._buffer_size = 0
        self._buffer_high = self.default_buffer_size
        self._buffer_low = self.default_buffer_size // 2
        self._offset = 0
        self._eof = False
        self._error = None

    @property
    def eof(self):
        return self._buffer_size == 0 and self._eof

    @property
    def error(self):
        return self._buffer_size == 0 and self._error

    def get_buffer_size(self):
        """Return the size of the buffer."""
        return self._buffer_size

    def set_buffer_limits(self, high=None, low=None):
        """Set the low and high watermarks for the read buffer."""
        if high is None:
            high = self.default_buffer_size
        if low is None:
            low = high // 2
        self._buffer_high = high
        self._buffer_low = low

    def feed(self, data):
        """Add *data* to the buffer."""
        self._buffers.append(data)
        self._buffer_size += len(data)
        self._maybe_pause_transport()
        self._can_read.set()

    def feed_eof(self):
        """Set the EOF condition."""
        self._eof = True
        self._can_read.set()

    def feed_error(self, exc):
        """Set the error condition to *exc*."""
        self._error = exc
        self._can_read.set()

    def _maybe_resume_transport(self):
        if self._transport is None:
            return
        if self._buffer_size <= self._buffer_low:
            self._transport.resume_reading()

    def _maybe_pause_transport(self):
        if self._transport is None:
            return
        if self._buffer_size > self._buffer_high:
            self._transport.pause_reading()

    @switchpoint
    def get_chunk(self, size=-1, delim=None):
        # Get a single chunk of data. The chunk will be at most *size* bytes.
        # If *delim* is provided, then return a partial chunk if it contains
        # the delimiter.
        if size != 0 and not self._can_read.wait(self._timeout):
            raise Timeout('timeout waiting for data')
        if not self._buffers:
            return b''  # EOF or error
        # Clamp the current buffer to *size* bytes.
        endpos = len(self._buffers[0])
        if size == -1:
            size = endpos
        if self._offset + size < endpos:
            endpos = self._offset + size
        # Reduce it even further if the delimiter is found
        if delim:
            pos = self._buffers[0].find(delim, self._offset, endpos)
            if pos != -1:
                endpos = pos + len(delim)
        nbytes = endpos - self._offset
        # Try to move a buffer instead of copying.
        if self._offset == 0 and endpos == len(self._buffers[0]):
            chunk = self._buffers.pop(0)
        else:
            chunk = self._buffers[0][self._offset:endpos]
            self._offset = endpos
            if self._offset == len(self._buffers[0]):
                del self._buffers[0]
                self._offset = 0
        # Adjust buffer size and notify callback
        self._buffer_size -= nbytes
        self._maybe_resume_transport()
        # If there's no data and no error, clear the reading indicator.
        if not self._buffers and not self._eof and not self._error:
            self._can_read.clear()
        return chunk


class Stream(BufferedIOBase):
    """
    A byte stream.

    This class implements buffered, flow controlled and blocking read/write
    access on top of a transport.

    A stream works with ``bytes`` instances. To create a stream that works with
    unicode strings, you can wrap it with a :class:`io.TextIOWrapper`.
    """

    def __init__(self, transport, mode='rw', autoclose=False, timeout=None):
        """The *transport* argument specifies the transport on top of which to
        create the stream.

        The *mode* argument can be ``'r'`` for a read-only stream, ``'w'`` for
        a write-only stream, or ``'rw'`` for a read-write stream.

        The *autoclose* argument controls whether the underlying transport will
        be closed in the :meth:`close` method. Be careful with this as the
        close method is called from the :class:`io.BufferedIOBase` destructor,
        which may lead to unexpected closing of the transport when the stream
        goes out of scope.
        """
        self._transport = transport
        self._readable = 'r' in mode
        self._writable = 'w' in mode
        if self._readable:
            self._buffer = StreamBuffer(transport, timeout)
        self._autoclose = autoclose
        self._closed = False

    def readable(self):
        """Return whether the stream is readable."""
        return self._readable

    def writable(self):
        """Return whether the stream is writable."""
        return self._writable

    @property
    def closed(self):
        """Return whether the stream is closed."""
        return self._closed

    @property
    def buffer(self):
        """Return the :class:`StreamBuffer` for this stream."""
        if self._readable:
            return self._buffer

    def _check_readable(self):
        # Check that the transport is open and is readable
        if self._closed:
            raise StreamError('stream is closed')
        if not self._readable:
            raise StreamError('stream is not readable')

    def _check_writable(self):
        # Check that the transport is open and is writable
        if self._closed:
            raise StreamError('stream is closed')
        elif not self._writable:
            raise StreamError('stream is not writable')

    @switchpoint
    def read(self, size=-1):
        """Read up to *size* bytes.

        This function reads from the buffer multiple times until the requested
        number of bytes can be satisfied. This means that this function may
        block to wait for more data, even if some data is available. The only
        time a short read is returned, is on EOF or error.

        If *size* is not specified or negative, read until EOF.
        """
        self._check_readable()
        chunks = []
        bytes_read = 0
        bytes_left = size
        while True:
            chunk = self._buffer.get_chunk(bytes_left)
            if not chunk:
                break
            chunks.append(chunk)
            bytes_read += len(chunk)
            if bytes_read == size or not chunk:
                break
            if bytes_left > 0:
                bytes_left -= len(chunk)
        # If EOF was set, always return that instead of any error.
        if not chunks and not self._buffer.eof and self._buffer.error:
            raise compat.saved_exc(self._buffer.error)
        return b''.join(chunks)

    @switchpoint
    def read1(self, size=-1):
        """Read up to *size* bytes.

        This function reads from the buffer only once. It is useful in case you
        need to read a large input, and want to do so efficiently. If *size* is
        big enough, then this method will return the chunks passed into the
        memory buffer verbatim without any copying or slicing.
        """
        self._check_readable()
        chunk = self._buffer.get_chunk(size)
        if not chunk and not self._buffer.eof and self._buffer.error:
            raise compat.saved_exc(self._buffer.error)
        return chunk

    @switchpoint
    def readline(self, limit=-1, delim=b'\n'):
        """Read a single line.

        If EOF is reached before a full line can be read, a partial line is
        returned. If *limit* is specified, at most this many bytes will be read.
        """
        self._check_readable()
        chunks = []
        while True:
            chunk = self._buffer.get_chunk(limit, delim)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(delim):
                break
            if limit >= 0:
                limit -= len(chunk)
                if limit == 0:
                    break
        if not chunks and not self._buffer.eof and self._buffer.error:
            raise compat.saved_exc(self._buffer.error)
        return b''.join(chunks)

    @switchpoint
    def readlines(self, hint=-1):
        """Read lines until EOF, and return them as a list.

        If *hint* is specified, then stop reading lines as soon as the total
        size of all lines exceeds *hint*.
        """
        self._check_readable()
        lines = []
        chunks = []
        bytes_read = 0
        while True:
            chunk = self._buffer.get_chunk(-1, b'\n')
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b'\n'):
                lines.append(b''.join(chunks))
                del chunks[:]
                bytes_read += len(lines[-1])
            if hint >= 0 and bytes_read > hint:
                break
        if chunks:
            lines.append(b''.join(chunks))
        if not lines and not self._buffer.eof and self._buffer.error:
            raise compat.saved_exc(self._buffer.error)
        return lines

    @switchpoint
    def __iter__(self):
        """Generate lines until EOF is reached."""
        while True:
            line = self.readline()
            if not line:
                break
            yield line

    @switchpoint
    def write(self, data):
        """Write *data* to the transport.

        This method will block if the transport's write buffer is at capacity.
        """
        self._check_writable()
        self._transport._can_write.wait()
        self._transport.write(data)

    @switchpoint
    def writelines(self, seq):
        """Write the elements of the sequence *seq* to the transport.

        This method will block if the transport's write buffer is at capacity.
        """
        self._check_writable()
        for line in seq:
            self._transport._can_write.wait()
            self._transport.write(line)

    @switchpoint
    def write_eof(self):
        """Close the write direction of the transport.

        This method will block if the transport's write buffer is at capacity.
        """
        self._check_writable()
        self._transport._can_write.wait()
        self._transport.write_eof()

    @switchpoint
    def close(self):
        """Close the stream.

        If *autoclose* was passed to the constructor then the underlying
        transport will be closed as well.
        """
        if self._closed:
            return
        if self._autoclose:
            self._transport.close()
            self._transport._closed.wait()
        self._transport = None
        self._closed = True


class StreamProtocol(Protocol):
    """Byte stream protocol."""

    def __init__(self, timeout=None):
        """The *timeout* argument specifies a default timeout for protocol
        operations."""
        super(StreamProtocol, self).__init__(timeout=timeout)
        self._stream = None

    @property
    def stream(self):
        """A :class:`Stream` instance, providing blocking, flow controlled read
        and write access to the underlying transport."""
        return self._stream

    def connection_made(self, transport):
        # Protocol callback
        self._stream = Stream(transport, autoclose=True, timeout=self._timeout)
        self._transport = transport

    def data_received(self, data):
        # Protocol callback
        self._stream.buffer.feed(data)

    def eof_received(self):
        # Protocol callback
        self._stream.buffer.feed_eof()
        # I believe the most natural behavior for a stream is not to close the
        # write write direction when an EOF is received. Without this, a simple
        # echo server would not be possible. This behavior is similar to a
        # file. If EOF is reached on read, you can still write to it. Also is
        # is easy to implement autoclose in the stream handler if needed.
        return True  # Means do not autoclose.

    def connection_lost(self, exc=None):
        # Protocol callback.
        if exc:
            self._stream.buffer.feed_error(exc)
        else:
            # eof_received() is not guaranteed to happen. So if there is no error
            # make sure we set the EOF condition on the stream.
            self._stream.buffer.feed_eof()
        self._transport = None


class StreamClient(Client):
    """A stream client."""

    def __init__(self, timeout=None):
        super(StreamClient, self).__init__(self._create_protocol, timeout=timeout)

    def _create_protocol(self):
        return StreamProtocol(timeout=self._timeout)

    @property
    def stream(self):
        """An alias for ``self.protocol.reader``"""
        if not self.protocol:
            raise ProtocolError('not connected')
        return self.protocol.stream

    delegate_method(stream, Stream.read)
    delegate_method(stream, Stream.read1)
    delegate_method(stream, Stream.readline)
    delegate_method(stream, Stream.readlines)
    delegate_method(stream, Stream.write)
    delegate_method(stream, Stream.writelines)
    delegate_method(stream, Stream.write_eof)


class StreamServer(Server):
    """A stream server."""

    def __init__(self, stream_handler, timeout=None):
        """The *stream_handler* argument is a handler function to handle client
        connections. The handler will be called as ``stream_handler(stream,
        transport, protocol)``. The handler for each connection will run in a
        separate fiber so it can use blocking I/O on the stream. When the
        handler returns, the stream is closed.

        See :ref:`example-stream-server` for an example.
        """
        super(StreamServer, self).__init__(StreamProtocol, timeout=timeout)
        self._stream_handler = stream_handler
        self._dispatchers = {}

    def connection_made(self, transport, protocol):
        self._dispatchers[transport] = spawn(self._dispatch_stream, transport, protocol)

    def _dispatch_stream(self, transport, protocol):
        # Stream dispatcher, runs in a separate Fiber.
        self._log.debug('stream handler started')
        try:
            self._stream_handler(protocol.stream, transport, protocol)
        except Cancelled:
            self._log.debug('stream handler cancelled')
        except Exception:
            self._log.exception('uncaught exception in stream handler')
        transport.close()
        self._log.debug('stream handler exiting')

    def connection_lost(self, transport, protocol, exc=None):
        dispatcher = self._dispatchers.pop(transport)
        dispatcher.cancel()
