#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import six

import gruvi
from .sync import Event
from .errors import Cancelled
from .protocols import Protocol
from .endpoints import Client, Server, add_protocol_method
from .hub import switchpoint
from .util import docfrom

__all__ = ['StreamReader', 'StreamProtocol', 'StreamClient', 'StreamServer']


class StreamReader(object):
    """A stream reader.

    This is a blocking interface that provides :meth:`read`, :meth:`readline`
    and similar methods on top of a memory buffer.
    """

    def __init__(self, on_buffer_size_change=None):
        self._can_read = Event()
        self._buffers = []
        self._buffer_size = 0
        self._offset = 0
        self._eof = False
        self._error = None
        self._on_buffer_size_change = on_buffer_size_change

    @property
    def buffer_size(self):
        """Return the amount of bytes currently in the buffer."""
        return self._buffer_size

    @property
    def eof(self):
        """Return whether the stream is currently at end-of-file."""
        return self._eof and self._buffer_size == 0

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
    def _read_until(self, delim, limit=-1):
        """Read until *delim*, or until EOF if *delim* is not provided.
        If *limit* is positive then read at most this many bytes.
        """
        chunks = []
        bytes_read = 0
        while True:
            # Special case for limit == 0
            if limit != 0:
                self._can_read.wait()
            # _can_read is set: we have data, or there is an EOF of error
            if not self._buffers:
                break
            # Find start and end offset in current buffer (if any)
            pos = self._buffers[0].find(delim, self._offset) if delim else -1
            endpos = len(self._buffers[0]) if pos < 0 else pos + len(delim)
            nbytes = endpos - self._offset
            # Reading too many bytes?
            if limit >= 0 and bytes_read + nbytes > limit:
                nbytes = limit - bytes_read
                endpos = self._offset + nbytes
            # Try to move a buffer instead of copying.
            if self._offset == 0 and endpos == len(self._buffers[0]):
                chunks.append(self._buffers.pop(0))
            else:
                chunks.append(self._buffers[0][self._offset:endpos])
                self._offset = endpos
                if self._offset == len(self._buffers[0]):
                    del self._buffers[0]
                    self._offset = 0
            # Adjust buffer
            bytes_read += nbytes
            oldsize = self._buffer_size
            self._buffer_size -= nbytes
            if self._on_buffer_size_change:
                self._on_buffer_size_change(self, oldsize, self._buffer_size)
            if not self._buffers and not self._eof and not self._error:
                self._can_read.clear()
            # Done? If there is no delimiter, prefer to return only one chunk
            # as a short write to prevent copying.
            if pos >= 0 or bytes_read == limit \
                        or limit >= 0 and not delim \
                        or limit < 0 and (self._eof or self._error) and not self._buffers:
                break
        if len(chunks) == 1:
            return chunks[0]
        elif self._error and not self._eof and not chunks:
            raise self._error
        return b''.join(chunks)

    @switchpoint
    def read(self, size=-1):
        """Read up to *size* bytes.

        If *size* is not specified or negative, read until EOF.
        """
        return self._read_until(b'', size)

    @switchpoint
    def readline(self, limit=-1):
        """Read a single line.

        If EOF is reached before a full line can be read, a partial line is
        returned. If *limit* is specified, at most this many bytes will be read.
        """
        return self._read_until(b'\n', limit)

    @switchpoint
    def readlines(self, hint=-1):
        """Read lines until EOF, and return them as a list.

        If *hint* is specified, then lines will be read until their total size
        will be equal to or larger than *hint*, or until EOF occurs.
        """
        lines = []
        bytes_read = 0
        while True:
            try:
                line = self.readline()
            except Exception:
                # If there's already some lines read, we return those without
                # an exception first. Future invocatations of methods on
                # StreamReader will raise the exception again.
                if self._error and lines:
                    break
                six.reraise(*sys.exc_info())
            if not line:
                break
            lines.append(line)
            bytes_read += len(line)
            if hint >= 0 and bytes_read > hint:
                break
        if not lines and self._error:
            raise self._error
        return lines

    @switchpoint
    def __iter__(self):
        """Generate lines until EOF is reached."""
        while True:
            line = self.readline()
            if not line:
                break
            yield line


class StreamProtocol(Protocol):
    """Byte stream protocol."""

    def __init__(self):
        super(StreamProtocol, self).__init__()
        self._reader = StreamReader(self._update_read_buffer)

    def data_received(self, data):
        # Protocol callback
        assert self._reading is True
        self._reader.feed(data)

    def eof_received(self):
        # Protocol callback
        self._reader.feed_eof()
        # Always pass the EOF to the handler
        return True

    def connection_lost(self, exc):
        # Protocol callback
        self._reader.feed_eof()
        super(StreamProtocol, self).connection_lost(exc)
        if self._error:
            self._reader.feed_error(self._error)

    def _update_read_buffer(self, reader, oldsize, newsize):
        """Update the read buffer size and pause/resume reading."""
        self._read_buffer_size = newsize
        self.read_buffer_size_changed()

    @docfrom(StreamReader.read)
    @switchpoint
    def read(self, size=-1):
        return self._reader.read(size)

    @docfrom(StreamReader.readline)
    @switchpoint
    def readline(self, limit=-1):
        return self._reader.readline(limit)

    @docfrom(StreamReader.readlines)
    @switchpoint
    def readlines(self, hint=-1):
        return self._reader.readlines(hint)

    @docfrom(StreamReader.__iter__)
    @switchpoint
    def __iter__(self):
        return self._reader.__iter__()


class StreamClient(Client):
    """A stream client."""

    def __init__(self, timeout=None):
        super(StreamClient, self).__init__(StreamProtocol)

    add_protocol_method(StreamProtocol.read, globals(), locals())
    add_protocol_method(StreamProtocol.readline, globals(), locals())
    add_protocol_method(StreamProtocol.readlines, globals(), locals())
    add_protocol_method(StreamProtocol.__iter__, globals(), locals())

    add_protocol_method(StreamProtocol.write, globals(), locals())
    add_protocol_method(StreamProtocol.writelines, globals(), locals())
    add_protocol_method(StreamProtocol.write_eof, globals(), locals())


class StreamServer(Server):
    """A stream server."""

    def __init__(self, stream_handler, timeout=None):
        super(StreamServer, self).__init__(StreamProtocol)
        self._stream_handler = stream_handler
        self._dispatchers = {}

    def connection_made(self, transport, protocol):
        self._dispatchers[protocol] = gruvi.spawn(self._dispatch_stream, transport, protocol)

    def _dispatch_stream(self, transport, protocol):
        self._log.debug('stream handler started')
        try:
            self._stream_handler(protocol)
        except Cancelled:
            self._log.debug('stream handler cancelled')
        except Exception:
            self._log.exception('uncaught exception in stream handler')
        transport.close()
        self._log.debug('stream handler exiting')

    def connection_lost(self, transport, protocol, exc=None):
        dispatcher = self._dispatchers.pop(protocol)
        dispatcher.cancel()
