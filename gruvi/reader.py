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
from .fiber import ConditionSet


class Reader(io.BufferedIOBase):
    """A buffered, blocking reader.

    Data is fed into the reader with the :meth:`_feed` method. It can the be
    read back again using the :meth:`read`, :meth:`readline` and related
    methods. The methods that read data are all switchpoints and will block in
    case a read cannot be satisified.
    """

    def __init__(self, on_size_change=None):
        """Create a new reader."""
        super(Reader, self).__init__()
        self._buffers = collections.deque()
        self._offset = 0
        self._eof = False
        self._error = None
        self._buffer_size = 0
        self._on_size_change = on_size_change
        self._events = ConditionSet()

    def _adjust_size(self, delta):
        """Adjust the buffer size and fire the callback if any."""
        oldsize = self._buffer_size
        if delta:
            self._buffer_size += delta
        else:
            self._buffer_size = 0
        if self._on_size_change:
            self._on_size_change(oldsize, self._buffer_size)

    def _feed(self, data):
        """Feed *data* into the reader."""
        if data:
            self._buffers.append(data)
            self._adjust_size(len(data))
            self._events.notify('InputReceived')
        else:
            self._eof = True
            self._events.notify('EOF')

    def _set_error(self, error):
        """Set an error state on the reader."""
        self._error = error
        self._events.notify('Error')

    def _get(self, size=None):
        """Get one buffer, of length no more than *size*."""
        if not self._buffers:
            return b''
        if size is None:
            size = len(self._buffers[0])
        buf = self._buffers[0][self._offset:self._offset+size]
        self._offset += size
        if self._offset >= len(self._buffers[0]):
            self._offset = 0
            self._buffers.popleft()
        self._adjust_size(-len(buf))
        return buf

    def _getall(self):
        """Return all buffers."""
        if not self._buffers:
            return b''
        if self._offset:
            self._buffers[0] = self._buffers[0][self._offset:]
        bufs = self._buffers
        self._buffers = collections.deque()
        self._adjust_size(-self._buffer_size)
        return bufs

    def _find(self, s):
        """Find the string *s* in the buffers."""
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

    @switchpoint
    def read(self, size=None):
        """Read up to *size* bytes.
        
        If *size* is not specified, read until EOF.
        """
        if not self._buffers:
            if self._eof:
                return b''
            elif self._error:
                raise self._error
        if size is None:
            if not self._eof and not self._error:
                self._events.wait('EOF', 'Error')
            if self._error:
                raise self._error
            buf = b''.join(self._getall())
        else:
            if len(self._buffers) == 0:
                self._events.wait('InputReceived', 'EOF', 'Error')
            if self._error:
                raise self._error
            buf = self._get(size)
        return buf

    @switchpoint
    def readline(self, limit=-1):
        """Read a single line.

        If EOF is reached before a full line can be read, a partial line is
        returned. If *limit* is specified, at most *limit* bytes will be read.
        """
        chunks = []
        while True:
            pos = self._find('\n')
            if pos != -1:
                nbytes = pos+1
                while nbytes > 0:
                    chunks.append(self._get(nbytes))
                    nbytes -= len(chunk)
                break
            chunks.extend(self._getall())
            if self._eof or self._error:
                break
            self._wait('InputReceived', 'EOF')
        if not chunks and self._error:
            raise self._error
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
