#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import textwrap
from io import BufferedIOBase

from . import compat
from .sync import Event
from .errors import Cancelled
from .fibers import spawn
from .protocols import Protocol, ProtocolError
from .endpoints import Client, Server, add_method
from .hub import switchpoint

__all__ = ['StreamReader', 'StreamWriter', 'ReadWriteStream', 'StreamProtocol',
           'StreamClient', 'StreamServer']


class StreamReader(BufferedIOBase):
    """A stream reader.

    This is a utility class that is used to implement a blocking reader
    interface on top of a memory buffer.

    A stream reader always operates on ``bytes`` instances. To create a reader
    that works on unicode strings, you can wrap it with a
    :class:`io.TextIOWrapper`.
    """

    def __init__(self, on_buffer_size_change=None, timeout=None):
        self._on_buffer_size_change = on_buffer_size_change
        self._timeout = timeout
        self._can_read = Event()
        self._buffers = []
        self._buffer_size = 0
        self._offset = 0
        self._eof = False
        self._error = None

    readable = lambda self: True

    @property
    def buffer_size(self):
        """Return the amount of bytes currently in the buffer."""
        return self._buffer_size

    @property
    def eof(self):
        """Return whether the stream is currently at end-of-file."""
        return self._eof and self._buffer_size == 0

    closed = eof

    def feed(self, data):
        """Add *data* to the buffer."""
        self._buffers.append(data)
        oldsize = self._buffer_size
        self._buffer_size += len(data)
        if self._on_buffer_size_change:
            self._on_buffer_size_change(self, oldsize, self._buffer_size)
        self._can_read.set()

    def feed_eof(self):
        """Set the EOF condition."""
        self._eof = True
        self._can_read.set()

    def feed_error(self, exc):
        """Set the error condition to *exc*."""
        self._error = exc
        self._can_read.set()

    @switchpoint
    def _get_chunk(self, size=-1, delim=None):
        # Get a single chunk of data. The chunk will be at most *size* bytes.
        # If *delim* is provided, then return a partial chunk if it contains
        # the delimiter.
        if size != 0:
            self._can_read.wait(self._timeout)
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
        oldsize = self._buffer_size
        self._buffer_size -= nbytes
        if self._on_buffer_size_change:
            self._on_buffer_size_change(self, oldsize, self._buffer_size)
        # If there's no data and no error, clear the reading indicator.
        if not self._buffers and not self._eof and not self._error:
            self._can_read.clear()
        return chunk

    @switchpoint
    def read(self, size=-1):
        """Read up to *size* bytes.

        This function reads from the buffer multiple times until the requested
        number of bytes can be satisfied. This means that this function may
        block to wait for more data, even if some data is available. The only
        time a short read is returned, is on EOF or error.

        If *size* is not specified or negative, read until EOF.
        """
        chunks = []
        bytes_read = 0
        bytes_left = size
        while True:
            chunk = self._get_chunk(bytes_left)
            if not chunk:
                break
            chunks.append(chunk)
            bytes_read += len(chunk)
            if bytes_read == size or not chunk:
                break
            if bytes_left > 0:
                bytes_left -= len(chunk)
        if not chunks and self._error:
            raise compat.saved_exc(self._error)
        return b''.join(chunks)

    @switchpoint
    def read1(self, size=-1):
        """Read up to *size* bytes.

        This function reads from the buffer only once. It is useful in case you
        need to read a large input, and want to do so efficiently. If *size* is
        big enough, then this method will return the chunks passed into the
        memory buffer verbatim without any copying or slicing.
        """
        chunk = self._get_chunk(size)
        if not chunk and self._error:
            raise compat.saved_exc(self._error)
        return chunk

    @switchpoint
    def readline(self, limit=-1, delim=b'\n'):
        """Read a single line.

        If EOF is reached before a full line can be read, a partial line is
        returned. If *limit* is specified, at most this many bytes will be read.
        """
        chunks = []
        while True:
            chunk = self._get_chunk(limit, delim)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(delim):
                break
            if limit >= 0:
                limit -= len(chunk)
                if limit == 0:
                    break
        if not chunks and self._error:
            raise compat.saved_exc(self._error)
        return b''.join(chunks)

    @switchpoint
    def readlines(self, hint=-1):
        """Read lines until EOF, and return them as a list.

        If *hint* is specified, then stop reading lines as soon as the total
        size of all lines exceeds *hint*.
        """
        lines = []
        chunks = []
        bytes_read = 0
        while True:
            chunk = self._get_chunk(-1, b'\n')
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
        if not lines and self._error:
            raise compat.saved_exc(self._error)
        return lines

    @switchpoint
    def __iter__(self):
        """Generate lines until EOF is reached."""
        while True:
            line = self.readline()
            if not line:
                break
            yield line


class StreamWriter(BufferedIOBase):
    """A stream writer.

    This class implements flow control in the write direction for a
    transport/protocol pair.

    A stream writer always operates on ``bytes`` instances. To create a writer
    that works on unicode strings, you can wrap it with a
    :class:`io.TextIOWrapper`.
    """

    def __init__(self, transport, protocol):
        self._transport = transport
        self._protocol = protocol

    writable = lambda self: True
    closed = property(lambda self: self._transport is None)

    @switchpoint
    def write(self, data):
        """Write *data* to the transport.

        This method just submits the write to the transport. The transport
        itself will issue the write at a later time. If there's an error once
        the write is issued, it an exception will be set on the transport, that
        will be re-raised by future :meth:`write` and other method.

        This method may block if the protocol is currently blocked, i.e. if the
        protocol's :meth:`~gruvi.BaseProtocol.pause_writing` method was called
        by the transport. In this case, the write block until the protocol's
        :meth:`~gruvi.BaseProtocol.resume_writing` method is called.
        """
        self._protocol._may_write.wait()
        if self._transport._error:
            raise compat.saved_exc(self._transport._error)
        elif self._transport is None:
            raise ProtocolError('not connected')
        self._transport.write(data)

    @switchpoint
    def writelines(self, seq):
        """Write the elements of the sequence *seq* to the transport.

        This method implements flow control as described in :meth:`write`.
        """
        for line in seq:
            self._protocol._may_write.wait()
            if self._protocol._error:
                raise compat.saved_exc(self._transport._error)
            elif self._transport is None:
                raise ProtocolError('not connected')
            self._transport.write(line)

    @switchpoint
    def write_eof(self):
        """Close the write direction of the transport.

        This method implements flow control as described in :meth:`write`. The
        EOF will only be written when the protocol is not paused.
        """
        self._protocol._may_write.wait()
        if self._transport._error:
            raise compat.saved_exc(self._transport._error)
        elif self._transport is None:
            raise ProtocolError('not connected')
        self._transport.write_eof()

    @switchpoint
    def close(self):
        """Close the transport.

        This method will wait until all outstanding data in the transport is
        flushed, and the transport is closed by the event loop.
        """
        if self._transport is None:
            return
        self._transport.close()
        self._protocol._closed.wait()


class ReadWriteStream(BufferedIOBase):
    """A read-write stream.

    This is an adapter class that creates a read-write stream on top of a
    :class:`StreamReader` and a :class:`StreamWriter`.
    """

    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer
        self.read = reader.read
        self.read1 = reader.read1
        self.readline = reader.readline
        self.readlines = reader.readlines
        self.__iter__ = reader.__iter__
        self.write = writer.write
        self.writelines = writer.writelines
        self.write_eof = writer.write_eof
        self.close = writer.close

    readable = lambda self: True
    writable = lambda self: True
    closed = property(lambda self: self._writer.closed)


class StreamProtocol(Protocol):
    """Byte stream protocol."""

    def __init__(self, timeout=None):
        super(StreamProtocol, self).__init__(timeout=timeout)
        self._stream = None

    @property
    def stream(self):
        """A :class:`ReadWriteStream` instance that provides blocking, flow
        controlled read and write access to the underlying transport."""
        return self._stream

    def _update_read_buffer(self, reader, oldsize, newsize):
        """Update the read buffer size and pause/resume reading."""
        self._read_buffer_size = newsize
        self.read_buffer_size_changed()

    def connection_made(self, transport):
        super(StreamProtocol, self).connection_made(transport)
        self._reader = StreamReader(self._update_read_buffer, timeout=self._timeout)
        self._writer = StreamWriter(transport, self)
        self._stream = ReadWriteStream(self._reader, self._writer)

    def data_received(self, data):
        # Protocol callback
        assert self._reading is True
        self._reader.feed(data)

    def eof_received(self):
        # Protocol callback
        self._reader.feed_eof()
        # Always pass the EOF to the handler or the client and let it close.
        return True

    def connection_lost(self, exc):
        # Protocol callback
        self._reader.feed_eof()
        super(StreamProtocol, self).connection_lost(exc)
        # if self._error:
        #     self._reader.feed_error(self._error)


class StreamClient(Client):
    """A stream client."""

    def __init__(self, timeout=None):
        super(StreamClient, self).__init__(self._create_protocol, timeout=timeout)

    def _create_protocol(self):
        return StreamProtocol(timeout=self._timeout)

    @property
    def stream(self):
        """An alias for ``self.protocol.stream``"""
        if not self.protocol:
            raise ProtocolError('not connected')
        return self.connection[1].stream

    _stream_method = textwrap.dedent("""\
        def {name}{signature}:
            '''A alias for ``self.stream.{name}().``'''
            if not self.protocol:
                raise ProtocolError('not connected')
            return self.stream.{name}{arglist}
            """)

    add_method(_stream_method, StreamReader.read)
    add_method(_stream_method, StreamReader.read1)
    add_method(_stream_method, StreamReader.readline)
    add_method(_stream_method, StreamReader.readlines)
    add_method(_stream_method, StreamReader.__iter__)

    add_method(_stream_method, StreamWriter.write)
    add_method(_stream_method, StreamWriter.writelines)
    add_method(_stream_method, StreamWriter.write_eof)


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
        super(StreamServer, self).__init__(self._create_protocol, timeout=timeout)
        self._stream_handler = stream_handler
        self._dispatchers = {}

    def _create_protocol(self):
        return StreamProtocol(timeout=self._timeout)

    def connection_made(self, transport, protocol):
        self._dispatchers[protocol] = spawn(self._dispatch_stream, transport, protocol)

    def _dispatch_stream(self, transport, protocol):
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
        dispatcher = self._dispatchers.pop(protocol)
        dispatcher.cancel()
