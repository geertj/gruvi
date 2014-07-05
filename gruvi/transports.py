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

__all__ = ['TransportError', 'BaseTransport', 'Transport', 'DatagramTransport']


class TransportError(Error):
    """A transport error."""

    def __init__(self, message, errno=None):
        super(TransportError, self).__init__(message)
        self._errno = errno

    @property
    def errno(self):
        return self._errno

    @classmethod
    def from_errno(cls, errno):
        """Create a new instance from a :mod:`pyuv.errno` error code."""
        message = '{0}: {1}'.format(pyuv.errno.errorcode.get(errno, errno),
                                    pyuv.errno.strerror(errno))
        return cls(message, errno)


class BaseTransport(object):
    """Base class for :mod:`pyuv` based transports. There is no public
    constructor."""

    write_buffer_size = 65536

    def __init__(self, handle, mode):
        self._handle = handle
        self._readable = 'r' in mode
        self._writable = 'w' in mode
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
        return self._protocol.connection_made(self)

    def get_extra_info(self, name, default=None):
        """Get transport specific data.

        The following information is available for all transports:

        ==============  =================================================
        Name            Description
        ==============  =================================================
        ``'handle'``    The pyuv handle that is being wrapped.
        ``'sockname'``  The socket name i.e. the result of the
                        ``getsockname()`` system call.
        ``'peername'``  The peer name i.e. the result of the
                        ``getpeername()`` system call.
        ``'fd'``        The handle's file descriptor. Unix only.
        ==============  =================================================
        """
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
        elif name == 'winsize':
            if not isinstance(self._handle, pyuv.TTY):
                return default
            return self._handle.get_winsize()
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
    """A connection oriented transport."""

    def __init__(self, handle, mode='rw'):
        """
        The *handle* argument is the pyuv handle for which to create the
        transport. It must be a ``pyuv.Stream`` instance, so either a
        :class:`pyuv.TCP`, :class:`pyuv.Pipe` or a :class:`pyuv.TTY`.

        The *mode* argument specifies if this is transport is read-only
        (``'r'``), write-only (``'w'``) or read-write (``'rw'``).
        """
        if not isinstance(handle, pyuv.Stream):
            raise TypeError("handle: expecting a 'pyuv.Stream' instance, got {0!r}"
                                .format(type(handle).__name__))
        super(Transport, self).__init__(handle, mode)

    def start(self, protocol):
        events = super(Transport, self).start(protocol)
        if self._readable:
            self._handle.start_read(self._read_callback)
            self._reading = True
        return events

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
        elif not self._closing and data:
            self._protocol.data_received(data)

    def pause_reading(self):
        """Pause calling callbacks on the protocol."""
        # Note: pause_reading() and resume_reading() are allowed when _closing
        # is true (unlike e.g. write()). This makes it easier for our child
        # class SslTransport to enable reading when it is closing down.
        if not self._readable:
            raise TransportError('transport is not readable')
        elif self._error:
            raise compat.saved_exc(self._error)
        elif self._protocol is None:
            raise TransportError('transport not started')
        elif not self._reading:
            raise TransportError('not currently reading')
        self._handle.stop_read()
        self._reading = False

    def resume_reading(self):
        """Resume calling callbacks on the protocol."""
        if not self._readable:
            raise TransportError('transport is not readable')
        elif self._error:
            raise compat.saved_exc(self._error)
        elif self._protocol is None:
            raise TransportError('transport not started')
        elif self._reading:
            raise TransportError('already reading')
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
        if not self._writable:
            raise TransportError('transport is not writable')
        elif self._error:
            raise compat.saved_exc(self._error)
        elif self._closing or self._handle.closed:
            raise TransportError('transport is closing/closed')
        elif self._protocol is None:
            raise TransportError('transport not started')
        elif len(data) == 0:
            return
        if self._write_buffer_size > self._write_buffer_high:
            self._protocol.pause_writing()
            self._writing = False
        callback = functools.partial(self._on_write_complete, len(data))
        try:
            self._handle.write(data, callback)
        except pyuv.error.UVError as e:
            self._error = TransportError.from_errno(e.args[0])
            self.abort()
            raise compat.saved_exc(self._error)
        self._write_buffer_size += len(data)

    def writelines(self, seq):
        """Write all elements from *seq* to the transport."""
        for line in seq:
            self.write(line)

    def write_eof(self):
        """Shut down the write direction of the transport."""
        if not self._writable:
            raise TransportError('transport is not writable')
        elif self._error:
            raise compat.saved_exc(self._error)
        elif self._closing or self._handle.closed:
            raise TransportError('transport is closing/closed')
        elif self._protocol is None:
            raise RuntimeError('transport not started')
        callback = functools.partial(self._on_write_complete, 1)
        try:
            self._handle.shutdown(callback)
        except pyuv.error.UVError as e:
            self._error = TransportError.from_errno(e.args[0])
            self.abort()
            raise compat.saved_exc(self._error)
        self._write_buffer_size += 1

    def can_write_eof(self):
        """Whether this transport can close the write direction."""
        return True

    def get_extra_info(self, name, default=None):
        """Get transport specific data.

        In addition to the fields from :meth:`BaseTransport.get_extra_info`,
        the following information is also available:

        ==================  ===================================================
        Name                Description
        ==================  ===================================================
        ``'winsize'``       The terminal window size as a ``(cols, rows)``
                            tuple. Only available for :class:`pyuv.TTY`
                            handles.
        ``'unix_creds'``    The Unix credentials of the peer as a
                            ``(pid, uid, gid)`` tuple. Only available for
                            :class:`pyuv.Pipe` handles on Unix.
        ==================  ===================================================
        """
        if name == 'winsize':
            if not isinstance(self._handle, pyuv.TTY):
                return default
            return self._handle.get_winsize()
        elif name == 'unix_creds':
            if not isinstance(self._handle, pyuv.Pipe) or not hasattr(socket, 'SO_PEERCRED'):
                return default
            fd = self._handle._fileno()
            sock = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_DGRAM)  # will dup()
            creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
            sock.close()
            return struct.unpack('3i', creds)
        else:
            return super(Transport, self).get_extra_info(name, default)


class DatagramTransport(BaseTransport):
    """A datagram transport."""

    def __init__(self, handle, mode='rw'):
        """
        The *handle* argument is the pyuv handle for which to create the
        transport. It must be a :class:`pyuv.UDP` instance.

        The *mode* argument specifies if this is transport is read-only
        (``'r'``), write-only (``'w'``) or read-write (``'rw'``).
        """
        if not isinstance(handle, pyuv.UDP):
            raise TypeError("handle: expecting a 'pyuv.UDP' instance, got {0!r}"
                                .format(type(handle).__name__))
        super(DatagramTransport, self).__init__(handle, mode)

    def start(self, protocol):
        events = super(DatagramTransport, self).start(protocol)
        if self._readable:
            self._handle.start_recv(self._recv_callback)
        return events

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
        """Send a datagram containing *data* to *addr*.

        The *addr* argument may be omitted only if the handle was bound to a
        default remote address.
        """
        if not isinstance(data, bytes):
            raise TypeError("data: expecting a 'bytes' instance, got {0!r}"
                                .format(type(data).__name__))
        if not self._writable:
            raise TransportError('transport is not writable')
        elif self._closing or self._handle.closed:
            raise TransportError('transport is closing/closed')
        elif len(data) == 0:
            return
        self._write_buffer_size += len(data)
        if self._write_buffer_size > self._write_buffer_high:
            self._protocol.pause_writing()
            self._writing = False
        callback = functools.partial(self._on_send_complete, len(data))
        self._handle.send(addr, data, callback)
