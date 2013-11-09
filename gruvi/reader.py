#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

import io
import collections

from .hub import switchpoint
from .sync import Signal


class BufferList(object):
    """A list of buffers.

    This tries to be efficient and copy as little data as needed. A buffer is
    added to the buffer list using :meth:`feed`, and retreived using
    :meth:`get`. Unless requested otherwise by using the *size* argument to
    :meth:`get`, the bufers are added and removed from the buffer list without
    any copying or slicing.
    """

    def __init__(self):
        """Create a new buffer."""
        self._buffers = collections.deque()
        self._offset = 0
        self._eof = False
        self._error = None
        self._size = 0
        self._events = Signal()
        self._size_changed = Signal()

    @property
    def size(self):
        """The total size of all chunks."""
        return self._size

    @property
    def eof(self):
        """Whether EOF has been received.
        
        Note that there may still be unread data in the buffer.
        """
        return self._eof

    @property
    def error(self):
        """The error condition, if any."""
        return self._error

    @property
    def events(self):
        """Signal that is emitted when an event occurs.

        Signal arguments: ``event(event_name)``.The event name will be one of
        ``'InputReceived'``, ``'EOF'``, or ``'Error'``.
        """
        return self._events

    @property
    def size_changed(self):
        """Signal that is emitted when the buffer size changed.
        
        Signal arguments: ``size_changed(oldsize, newsize)``
        """
        return self._size_changed

    def feed(self, buf):
        """Append a new buffer to the buffer list."""
        if not buf:
            self.feed_eof()
            return
        self._buffers.append(buf)
        oldsize, self._size = self._size, self._size+len(buf)
        self.events.emit('InputReceived')
        self.size_changed.emit(oldsize, self._size)

    def feed_eof(self):
        """Feed an EOF into the buffer."""
        self._eof = True
        self.events.emit('EOF')

    def feed_error(self, error):
        """Set an error condition on the buffer."""
        self._error = error
        self.evens.emit('Error')

    def get(self, size=None):
        """Get one buffer, of length no more than *size*."""
        if not self._buffers:
            return b''
        if size is None or size > len(self._buffers[0])-self._offset:
            buf = self._buffers.popleft()
            if self._offset:
                buf = buf[self._offset:]
                self._offset = 0
        else:
            buf = self._buffers[0][self._offset:self._offset+size]
            self._offset += size
            if self._offset >= len(self._buffers[0]):
                self._buffers.popleft()
                self._offset = 0
        oldsize, self._size = self._size, self._size-len(buf)
        self.events.emit('InputReceived')
        self.size_changed.emit(oldsize, self._size)
        return buf

    def getall(self):
        """Return all sequence containing all buffers."""
        bufs = []
        if self._offset:
            assert len(self._buffers) > 0
            buf = self._buffers.popleft()
            bufs.append(buf[self._offset:])
            self._offset = 0
        while self._buffers:
            buf = self._buffers.popleft()
            bufs.append(buf)
        return bufs

    def find(self, s):
        """Find the string *s* in the buffer list."""
        pos = 0
        offset = self._offset
        for buf in self._buffers:
            found = buf.find(s, offset)
            if found != -1:
                pos += found
                break
            pos += len(buf) - offset
            offset = 0
        if not found:
            pos = -1
        return pos


class Reader(io.BufferedIOBase):
    """A buffered, blocking reader.

    This implements an :class:`io.BufferedIOBase` interface on top of a
    :class:`BufferList`.
    """

    def __init__(self, buffers):
        """Create a new reader."""
        super(Reader, self).__init__()
        self._buffers = buffers

    @switchpoint
    def read(self, size=None):
        """Read up to *size* bytes.
        
        If *size* is not specified, read until EOF.
        """
        bufs = self._buffers
        if bufs.size == 0:
            if bufs.eof:
                return b''
            elif bufs.error:
                raise bufs.error
        if size is None:
            if not bufs.eof and not bufs.error:
                bufs.events.wait(waitfor=('EOF', 'Error'))
            assert bufs.eof or bufs.error
            if bufs.size == 0 and bufs.error:
                raise bufs.error
            buf = b''.join(bufs.getall())
        else:
            if bufs.size == 0:
                bufs.events.wait()
            if bufs.size == 0 and bufs.error:
                raise bufs.error
            buf = bufs.get(size)
        return buf

    @switchpoint
    def readline(self, limit=-1):
        """Read a single line.

        If EOF is reached before a full line can be read, a partial line is
        returned. If *limit* is specified, at most *limit* bytes will be read.
        """
        chunks = []
        bufs = self._buffers
        while True:
            pos = bufs.find('\n')
            if pos != -1:
                nbytes = pos+1
                while nbytes > 0:
                    chunk = bufs.get(nbytes)
                    chunks.append(chunk)
                    nbytes -= len(chunk)
                break
            chunks.extend(bufs.getall())
            if bufs.eof or bufs.error:
                break
            bufs.events.wait()
        if not chunks and bufs.error:
            raise bufs.error
        return b''.join(chunks)

    @switchpoint
    def readlines(self, hint=-1):
        """Read lines until EOF, and return them as a list.

        If *hint* is specified, then lines will be read until their total size
        will be equal to or larger than *hint*.
        """
        lines = []
        bytes_read = 0
        while True:
            line = self.readline()
            if not line:
                break
            lines.append(line)
            bytes_read += len(line)
            if hint != -1 and bytes_read > hint:
                break
        return lines

    @switchpoint
    def __iter__(self):
        """Generate lines until EOF is reached."""
        while True:
            line = self.readline()
            if not line:
                break
            yield line
