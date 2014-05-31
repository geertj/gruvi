#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
import functools
import socket
import struct

from . import logging, compat
from .errors import Error

# Stream is not exposed by pyuv.
Stream = pyuv.TCP.__bases__[0]
UvError = pyuv.error.UVError

__all__ = ['UvError', 'TransportError', 'BaseTransport', 'Transport', 'DatagramTransport']


class TransportError(Error):
    """Transport error."""

    def __init__(self, message, errno=None):
        super(TransportError, self).__init__(message)
        self._errno = errno

    @property
    def errno(self):
        return self._errno

    @classmethod
    def from_errno(cls, errno, message=None):
        if message is None:
            message = '{0}: {1}'.format(pyuv.errno.errorcode.get(errno, errno),
                                        pyuv.errno.strerror(errno))

        return cls(message, errno)


class BaseTransport(object):
    """Base class for :mod:`pyuv` based transports."""

    write_buffer_size = 65536

    def __init__(self, handle):
        self._handle = handle
        self._protocol = None
        self._log = logging.get_logger()
        self._write_buffer_size = 0
        self._write_buffer_high = self.write_buffer_size
        self._write_buffer_low = self.write_buffer_size // 2
        self._closing = False
        self._error = None
        self._reading = False
        self._writing = True
        self._started = False

    def start(self, protocol):
        """Bind to *protocol* and start calling callbacks on it."""
        if self._protocol is not None:
            raise RuntimeError('already started')
        self._protocol = protocol
        self._protocol.connection_made(self)

    def get_extra_info(self, name, default=None):
        """Get transport specific data."""
        if name == 'handle':
            return self._handle
        elif name == 'sockname':
            return self._handle.getsockname()
        elif name == 'peername':
            if not hasattr(self._handle, 'getpeername'):
                return default
            return self._handle.getpeername()
        elif name == 'fd':
            fd = self._handle._fileno()
            return fd if fd >= 0 else None
        elif name == 'unix_creds':
            if not isinstance(self._handle, pyuv.Pipe) or not hasattr(socket, 'SO_PEERCRED'):
                return default
            fd = self._handle._fileno()
            sock = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_DGRAM)  # will dup()
            creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
            sock.close()
            return struct.unpack('3i', creds)
        else:
            return default

    def get_write_buffer_size(self):
        """Return the current write buffer size."""
        return self._write_buffer_size

    def set_write_buffer_limits(self, high=None, low=None):
        """Set the low and high watermark for the write buffer."""
        if high is None:
            high = self.write_buffer_size
        if low is None:
            low = high // 2
        if low > high:
            low = high
        self._write_buffer_high = high
        self._write_buffer_low = low

    def _on_close_complete(self, handle):
        # Callback used with handle.close().
        assert handle is self._handle
        self._protocol.connection_lost(self._error)
        self._protocol = None  # remove cycle to help garbage collection

    def close(self):
        """Close the transport after all oustanding data has been written."""
        if self._closing or self._handle.closed:
            return
        elif self._protocol is None:
            raise RuntimeError('transport not started')
        # If the write buffer is empty, close now. Otherwise defer to
        # _on_write_complete that will close when it's empty.
        if self._write_buffer_size == 0:
            self._handle.close(self._on_close_complete)
            assert self._handle.closed
        else:
            self._closing = True

    def abort(self):
        """Close the transport immediately."""
        if self._handle.closed:
            return
        elif self._protocol is None:
            raise RuntimeError('transport not started')
        self._handle.close(self._on_close_complete)
        assert self._handle.closed


class Transport(BaseTransport):
    """A stream transport.

    This is an adapter class that adapts the :class:`pyuv.Stream` API to a
    stream transport as specified in PEP 3156.
    """

    def __init__(self, handle):
        """
        The *handle* argument is the pyuv handle for which to create the
        transport. It must be a :class:`pyuv.Stream` instance.
        """
        if not isinstance(handle, Stream):
            raise TypeError("handle: expecting a 'pyuv.Stream' instance, got {0!r}"
                                .format(type(handle).__name__))
        super(Transport, self).__init__(handle)

    def start(self, protocol):
        """Bind to *protocol* and start calling callbacks on it."""
        super(Transport, self).start(protocol)
        self._handle.start_read(self._read_callback)
        self._reading = True

    def _read_callback(self, handle, data, error):
        # Callback used with handle.start_read().
        assert handle is self._handle
        if self._error:
            self._log.warning('ignore read status {} after close', error)
        elif error == pyuv.errno.UV_EOF:
            if self._protocol.eof_received():
                self._log.debug('EOF received, protocol wants to continue')
            elif not self._closing:
                self._log.debug('EOF received, closing transport')
                self._error = TransportError('connection lost')
                self.close()
        elif error:
            self._log.warning('pyuv error {} in read callback', error)
            self._error = TransportError.from_errno(error)
            self.abort()
        elif not self._closing:
            self._protocol.data_received(data)

    def pause_reading(self):
        """Pause calling callbacks on the protocol."""
        # Note: pause_reading() and resume_reading() are allowed when _closing
        # is true (unlike e.g. write()). This makes it easier for our child
        # class SslTransport to enable reading when it is closing down.
        if self._error:
            raise self._error
        elif self._protocol is None:
            raise RuntimeError('transport not started')
        elif not self._reading:
            raise RuntimeError('not currently reading')
        self._handle.stop_read()
        self._reading = False

    def resume_reading(self):
        """Start calling callbacks on the protocol."""
        if self._error:
            raise self._error
        elif self._protocol is None:
            raise RuntimeError('transport not started')
        elif self._reading:
            raise RuntimeError('already reading')
        self._handle.start_read(self._read_callback)
        self._reading = True

    def _on_write_complete(self, datalen, handle, error):
        # Callback used with handle.write().
        assert handle is self._handle
        self._write_buffer_size -= datalen
        assert self._write_buffer_size >= 0
        if self._error:
            self._log.debug('write status {} after close', error)
        elif error and error != pyuv.errno.UV_ECANCELED:
            self._log.warning('pyuv error {} in write callback', error)
            self._error = TransportError.from_errno(error)
            self.abort()
        if not self._closing and not handle.closed and not self._writing \
                    and self._write_buffer_size <= self._write_buffer_low:
            self._protocol.resume_writing()
            self._writing = True
        if self._closing and self._write_buffer_size == 0:
            if not handle.closed:
                handle.close(self._on_close_complete)
            self._closing = False

    def write(self, data):
        """Write *data* to the transport."""
        if not isinstance(data, compat.bytes_types):
            raise TypeError("data: expecting a bytes-like instance, got {0!r}"
                                .format(type(data).__name__))
        if self._error:
            raise self._error
        elif self._closing or self._handle.closed:
            raise TransportError('transport is closing/closed')
        elif self._protocol is None:
            raise RuntimeError('transport not started')
        elif len(data) == 0:
            return
        self._write_buffer_size += len(data)
        if self._write_buffer_size > self._write_buffer_high:
            self._protocol.pause_writing()
            self._writing = False
        callback = functools.partial(self._on_write_complete, len(data))
        self._handle.write(data, callback)

    def writelines(self, seq):
        """Write all elements from *seq* to the transport."""
        for line in seq:
            self.write(line)

    def write_eof(self):
        """Shut down the write side of the transport."""
        if self._error:
            raise self._error
        elif self._closing or self._handle.closed:
            raise TransportError('transport is closing/closed')
        elif self._protocol is None:
            raise RuntimeError('transport not started')
        self._write_buffer_size += 1
        callback = functools.partial(self._on_write_complete, 1)
        self._handle.shutdown(callback)

    def can_write_eof(self):
        """Wether this transport can close the write direction."""
        return True


class DatagramTransport(BaseTransport):
    """A datagram transport.

    This is an adapter class that adapts the :class:`pyuv.UDP` API to a
    datagram transport as specified in PEP 3156.
    """

    def __init__(self, handle):
        """
        The *handle* argument is the pyuv handle for which to create the
        transport. It must be a :class:`pyuv.UDP` instance.
        """
        if not isinstance(handle, pyuv.UDP):
            raise TypeError("handle: expecting a 'pyuv.UDP' instance, got {0!r}"
                                .format(type(handle).__name__))
        super(DatagramTransport, self).__init__(handle)

    def start(self, protocol):
        """Bind to *protocol* and start calling callbacks on it."""
        super(DatagramTransport, self).start(protocol)
        self._handle.start_recv(self._recv_callback)

    def _recv_callback(self, handle, addr, flags, data, error):
        """Callback used with handle.start_recv()."""
        assert handle is self._handle
        if error:
            self._log.warning('pyuv error {} in recv callback', error)
            self._protocol.error_received(TransportError.from_errno(error))
        elif flags:
            assert flags & pyuv.UV_UDP_PARTIAL
            self._log.warning('ignoring partial datagram')
        elif data and not self._closing:
            self._protocol.datagram_received(data, addr)

    def _on_send_complete(self, datalen, handle, error):
        """Callback used with handle.send()."""
        assert handle is self._handle
        self._write_buffer_size -= datalen
        assert self._write_buffer_size >= 0
        if error and error != pyuv.errno.UV_ECANCELED:
            self._log.warning('pyuv error {} in sendto callback', error)
            self._protocol.error_received(TransportError.from_errno(error))
        if not self._closing and not self._writing and \
                    self._write_buffer_size <= self._write_buffer_low:
            self._protocol.resume_writing()
            self._writing = True
        if self._closing and self._write_buffer_size == 0:
            if not handle.closed:
                self._handle.close(self._on_close_complete)
            self._closing = False

    def sendto(self, data, addr=None):
        """Send a datagram.

        If *addr* is not specified, the handle must have been bound to a
        default remote address.
        """
        if not isinstance(data, bytes):
            raise TypeError("data: expecting a 'bytes' instance, got {0!r}"
                                .format(type(data).__name__))
        if self._closing or self._handle.closed:
            raise TransportError('transport is closing/closed')
        elif len(data) == 0:
            return
        self._write_buffer_size += len(data)
        if self._write_buffer_size > self._write_buffer_high:
            self._protocol.pause_writing()
            self._writing = False
        callback = functools.partial(self._on_send_complete, len(data))
        self._handle.send(addr, data, callback)
