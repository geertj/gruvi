#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
import contextlib
import socket
import struct

from . import logging, compat
from .util import docfrom
from .errors import Error
from .sync import Event

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
        message = '{}: {}'.format(pyuv.errno.errorcode.get(errno, errno),
                                    pyuv.errno.strerror(errno))
        return cls(message, errno)


class BaseTransport(object):
    """Base class for :mod:`pyuv` based transports. There is no public
    constructor."""

    default_write_buffer = 65536

    def __init__(self, handle, mode):
        self._handle = handle
        self._readable = 'r' in mode
        self._writable = 'w' in mode
        self._protocol = None
        self._server = None
        self._log = logging.get_logger()
        self._write_buffer_size = 0
        self._write_buffer_high = self.default_write_buffer
        self._write_buffer_low = self.default_write_buffer // 2
        self._closing = False
        self._error = None
        self._reading = False
        self._writing = False
        self._started = False
        self._can_write = Event()
        self._closed = Event()

    def start(self, protocol):
        """Bind to *protocol* and start calling callbacks on it. """
        if self._protocol is not None:
            raise TransportError('already started')
        self._protocol = protocol
        self._protocol.connection_made(self)
        if self._readable:
            self.resume_reading()
        if self._writable:
            self._writing = True
            self._can_write.set()

    def _check_status(self):
        # Check the status of the transport.
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._protocol is None:
            raise TransportError('transport not started')
        elif self._handle.closed:
            raise TransportError('transport was closed')

    def get_write_buffer_size(self):
        """Return the total number of bytes in the write buffer."""
        return self._write_buffer_size

    def get_write_buffer_limits(self):
        """Return the write buffer limits as a ``(low, high)`` tuple."""
        return self._write_buffer_low, self._write_buffer_high

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

    def _maybe_resume_protocol(self):
        # Called after the write buffer size decreased. Possibly resume the protocol.
        if self._closing or self._handle.closed or self._writing:
            return
        if self.get_write_buffer_size() <= self.get_write_buffer_limits()[0]:
            self._writing = True
            self._can_write.set()
            self._protocol.resume_writing()

    def _maybe_pause_protocol(self):
        # Called after the write buffer size increased. Possibly pause the protocol.
        if self._closing or self._handle.closed or not self._writing:
            return
        if self.get_write_buffer_size() > self.get_write_buffer_limits()[0]:
            self._writing = False
            self._can_write.clear()
            self._protocol.pause_writing()

    def resume_reading(self):
        """Resume calling callbacks on the protocol.

        As a relaxation from the requirements in Python asyncio, this method
        may be called even if reading was already paused, and also if a close
        is pending. This simplifies protocol design, especially in combination
        with SSL where reading may need to be enabled by the transport itself,
        without knowledge of the protocol, to complete handshakes.
        """
        raise NotImplementedError

    def pause_reading(self):
        """Pause calling callbacks on the protocol.

        This method may be called even if reading was already paused or a close
        is pending. See the note in :meth:`resume_reading`.
        """
        raise NotImplementedError

    def _maybe_close(self):
        # Check a pending close request and close.
        if not self._closing or self._write_buffer_size > 0:
            return
        if not self._handle.closed:
            self._handle.close(self._on_close_complete)
            assert self._handle.closed
        self._closing = False

    def _on_close_complete(self, handle):
        # Callback used with handle.close().
        assert handle is self._handle
        assert handle.closed
        if self._server is not None:
            self._server._on_close_complete(self, self._protocol, self._error)
        self._protocol.connection_lost(self._error)
        self._protocol = None  # remove cycle to help garbage collection
        self._closed.set()

    def close(self):
        """Close the transport after all oustanding data has been written."""
        if self._closing or self._handle.closed:
            return
        elif self._protocol is None:
            raise TransportError('transport not started')
        # If the write buffer is empty, close now. Otherwise defer to
        # _on_write_complete that will close when the buffer is empty.
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
            raise TransportError('transport not started')
        self._handle.close(self._on_close_complete)
        assert self._handle.closed

    def get_extra_info(self, name, default=None):
        """Get transport specific data.

        The following information is available for all transports:

        ==============  =================================================
        Name            Description
        ==============  =================================================
        ``'handle'``    The pyuv handle that is being wrapped.
        ==============  =================================================
        """
        if name == 'handle':
            return self._handle
        else:
            return default


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
            raise TypeError("handle: expecting a 'pyuv.Stream' instance, got {!r}"
                                .format(type(handle).__name__))
        super(Transport, self).__init__(handle, mode)

    @docfrom(BaseTransport.get_write_buffer_size)
    def get_write_buffer_size(self):
        # Return the size of the write buffer. Return the actual number of
        # outstanding bytes, which libuv keeps track of for us. Note that we
        # _also_ use self._write_buffer_size to keep track of the total number
        # of oustanding write requests.. This allows us to keep track of e.g.
        # write_eof() that doesn't write actual bytes.
        return self._handle.write_queue_size

    def _on_read_complete(self, handle, data, error):
        # Callback used with handle.start_read().
        assert handle is self._handle
        if self._error:
            self._log.warning('ignore read status {} after error', error)
        elif error == pyuv.errno.UV_EOF:
            if self._protocol.eof_received():
                self._log.debug('EOF received, protocol wants to continue')
            else:
                self._log.debug('EOF received, closing transport')
                self.close()
        elif error:
            self._log.warning('pyuv error {} in read callback', error)
            self._error = TransportError.from_errno(error)
            self.abort()
        elif data:
            self._protocol.data_received(data)

    @docfrom(BaseTransport.resume_reading)
    def resume_reading(self):
        # Resume reading
        self._check_status()
        if not self._readable:
            raise TransportError('transport is not readable')
        if not self._reading:
            self._handle.start_read(self._on_read_complete)
            self._reading = True

    @docfrom(BaseTransport.pause_reading)
    def pause_reading(self):
        # Pause reading
        self._check_status()
        if not self._readable:
            raise TransportError('transport is not readable')
        if self._reading:
            self._handle.stop_read()
            self._reading = False

    def _on_write_complete(self, handle, error):
        # Callback used with handle.write().
        assert handle is self._handle
        self._write_buffer_size -= 1
        assert self._write_buffer_size >= 0
        if self._error:
            self._log.debug('ignore write status {} after error', error)
        # UV_ECANCELED happens when a handle is closed that has a write backlog.
        # This happens when Transport.abort() is called.
        elif error and error != pyuv.errno.UV_ECANCELED:
            self._log.warning('pyuv error {} in write callback', error)
            self._error = TransportError.from_errno(error)
            self.abort()
        self._maybe_resume_protocol()
        self._maybe_close()

    def write(self, data):
        """Write *data* to the transport."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data: expecting a bytes-like instance, got {!r}"
                                .format(type(data).__name__))
        self._check_status()
        if not self._writable:
            raise TransportError('transport is not writable')
        if self._closing:
            raise TransportError('transport is closing')
        try:
            self._handle.write(data, self._on_write_complete)
        except pyuv.error.UVError as e:
            self._error = TransportError.from_errno(e.args[0])
            self.abort()
            raise compat.saved_exc(self._error)
        # We only keep track of the number of outstanding write requests
        # outselves. See note in get_write_buffer_size().
        self._write_buffer_size += 1
        self._maybe_pause_protocol()

    def writelines(self, seq):
        """Write all elements from *seq* to the transport."""
        for line in seq:
            self.write(line)

    def write_eof(self):
        """Shut down the write direction of the transport."""
        self._check_status()
        if not self._writable:
            raise TransportError('transport is not writable')
        if self._closing:
            raise TransportError('transport is closing')
        try:
            self._handle.shutdown(self._on_write_complete)
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
        ``'sockname'``      The socket name i.e. the result of the
                            ``getsockname()`` system call.
        ``'peername'``      The peer name i.e. the result of the
                            ``getpeername()`` system call.
        ``'winsize'``       The terminal window size as a ``(cols, rows)``
                            tuple. Only available for :class:`pyuv.TTY`
                            handles.
        ``'unix_creds'``    The Unix credentials of the peer as a
                            ``(pid, uid, gid)`` tuple. Only available for
                            :class:`pyuv.Pipe` handles on Unix.
        ==================  ===================================================
        """
        if name == 'sockname':
            if not hasattr(self._handle, 'getsockname'):
                return default
            try:
                return self._handle.getsockname()
            except pyuv.error.UVError:
                return default
        elif name == 'peername':
            if not hasattr(self._handle, 'getpeername'):
                return default
            try:
                return self._handle.getpeername()
            except pyuv.error.UVError:
                return default
        elif name == 'winsize':
            if not hasattr(self._handle, 'get_winsize'):
                return default
            try:
                return self._handle.get_winsize()
            except pyuv.error.UVError:
                return default
        elif name == 'unix_creds':
            # In case you're wondering, DBUS needs this.
            if not isinstance(self._handle, pyuv.Pipe) or not hasattr(socket, 'SO_PEERCRED'):
                return default
            try:
                fd = self._handle.fileno()
                sock = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_DGRAM)  # will dup()
                with contextlib.closing(sock):
                    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                            struct.calcsize('3i'))
            except socket.error:
                return default
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
            raise TypeError("handle: expecting a 'pyuv.UDP' instance, got {!r}"
                                .format(type(handle).__name__))
        super(DatagramTransport, self).__init__(handle, mode)

    @docfrom(BaseTransport.get_write_buffer_size)
    def get_write_buffer_size(self):
        # Return the size of the write buffer. See the note for the same method
        # in Transport.
        # This was recently added to pyuv, so don't put a hard dependency on
        # it. UDP buffering in the write direction very OS dependent anyway.
        return getattr(self._handle, 'send_queue_size', 0)

    def _on_recv_complete(self, handle, addr, flags, data, error):
        """Callback used with handle.start_recv()."""
        assert handle is self._handle
        if error:
            self._log.warning('pyuv error {} in recv callback', error)
            self._protocol.error_received(TransportError.from_errno(error))
        elif flags:
            assert flags & pyuv.UV_UDP_PARTIAL
            self._log.warning('ignoring partial datagram')
        elif data:
            self._protocol.datagram_received(data, addr)

    @docfrom(BaseTransport.resume_reading)
    def resume_reading(self):
        # Resume reading
        self._check_status()
        if not self._readable:
            raise TransportError('transport is not readable')
        if not self._reading:
            self._handle.start_recv(self._on_recv_complete)
            self._reading = True

    @docfrom(BaseTransport.pause_reading)
    def pause_reading(self):
        # Pause reading
        self._check_status()
        if not self._readable:
            raise TransportError('transport is not readable')
        if self._reading:
            self._handle.stop_recv()
            self._reading = False

    def _on_send_complete(self, handle, error):
        """Callback used with handle.send()."""
        assert handle is self._handle
        self._write_buffer_size -= 1
        assert self._write_buffer_size >= 0
        if self._error:
            self._log.debug('ignore sendto status {} after error', error)
        # See note in _on_write_complete() about UV_ECANCELED
        elif error and error != pyuv.errno.UV_ECANCELED:
            self._log.warning('pyuv error {} in sendto callback', error)
            self._protocol.error_received(TransportError.from_errno(error))
        self._maybe_resume_protocol()
        self._maybe_close()

    def sendto(self, data, addr=None):
        """Send a datagram containing *data* to *addr*.

        The *addr* argument may be omitted only if the handle was bound to a
        default remote address.
        """
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data: expecting a bytes-like instance, got {!r}"
                                .format(type(data).__name__))
        self._check_status()
        if not self._writable:
            raise TransportError('transport is not writable')
        try:
            self._handle.send(addr, data, self._on_send_complete)
        except pyuv.error.UVError as e:
            error = TransportError.from_errno(e.args[0])
            # Try to discern between permanent and transient errors. Permanent
            # errors close the transport. This list is very likely not complete.
            if error.errno != pyuv.errno.UV_EBADF:
                raise error
            self._error = error
            self.abort()
        self._write_buffer_size += 1
        self._maybe_pause_protocol()
