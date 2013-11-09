#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import errno
import socket
import logging
import collections
import ssl
import io
import pyuv

from .hub import get_hub

if hasattr(socket, 'socketpair'):
    socketpair = socket.socketpair
else:
    from .socketpair import socketpair

__all__ = ['SSL']


ssl_error_nb = frozenset((ssl.SSL_ERROR_WANT_READ, ssl.SSL_ERROR_WANT_WRITE))
socket_error_nb = frozenset((errno.EAGAIN, errno.EWOULDBLOCK))

if sys.platform.startswith('win'):
    socket_error_nb = frozenset(tuple(socket_error_nb) + (errno.WSAEWOULDBLOCK,))


def write_to_socket(sock, data):
    """Write as much of *data* to the socket as possible, retrying short writes
    due to EINTR only."""
    offset = 0
    while offset != len(data):
        try:
            nbytes = sock.send(data[offset:])
        except (io.BlockingIOError, socket.error) as e:
            if e.args[0] == errno.EINTR:
                continue
            elif e.args[0] in socket_error_nb:
                break
            raise
        offset += nbytes
    return offset

def read_from_socket(sock, bufsize):
    """Read as much data as possible from *sock*, using *bufsize* sized
    chunks. The result is returned as a list of buffers."""
    chunks = []
    while True:
        try:
            chunk = sock.recv(bufsize)
        except (io.BlockingIOError, socket.error) as e:
            if e.args[0] == errno.EINTR:
                continue
            elif e.args[0] in socket_error_nb:
                break
            raise
        chunks.append(chunk)
    return chunks


class SSLPipe(object):
    """An SSL "Pipe".

    The pipe communicates with an SSL protocol instance through memory buffers.
    It can be used to insert a security layer into an existing connection.

    The Pipe initially is in "unwrapped" mode which means that no SSL layer is
    inserted. To start SSL, call :meth:`start_handshake`. To shutdown SSL
    again, call :meth:`start_shutdown`.
    """

    bufsize = 32768

    # Internally we use a socketpair to communicate with an SSLSocket instance.
    # This is because as of Python 3.3 the _ssl module does not yet provide a
    # "Memory BIO". See also:
    # http://mail.python.org/pipermail/python-ideas/2012-November/017686.html

    (s_unwrapped, s_handshake, s_wrapped, s_shutdown) = range(4)

    def __init__(self, context=None, **sslargs):
        """Create a new SSL pipe.

        The *context* argument specifies an optional SSLContext instance to
        use. This requires Python >= 3.2. The *sslargs* keyword arguments are
        passed to ``SSLContext.wrap_socket`` if a context was provided, or to
        ``ssl.wrap_socket`` otherwise.
        """
        self._context = context
        self._sslargs = sslargs.copy()
        self._sslargs['do_handshake_on_connect'] = False
        self._state = self.s_unwrapped
        self._fragment = None
        self._sslsock = None
        self._create_socketpair()
        self._handshake_callback = None
        self._shutdown_callback = None

    @property
    def socket(self):
        """Return the SSLSocket instance."""
        return self._sslsock

    @property
    def state(self):
        """Return the SSLPipe state."""
        return self._state

    def _create_socketpair(self):
        """Create the socket pair."""
        self._sockets = socketpair()
        if hasattr(socket, '_socketobject'):
            # Python 2.x needs this extra indirection to fill in some
            # platform specific functionality..
            self._sockets = (socket._socketobject(_sock=self._sockets[0]),
                             socket._socketobject(_sock=self._sockets[1]))
        for sock in self._sockets:
            sock.setblocking(False)

    def _create_sslsock(self):
        """Create the SSL socket."""
        if self._context:
            self._sslsock = self._context.wrap_socket(self._sockets[1], **self._sslargs)
        else:
            self._sslsock = ssl.wrap_socket(self._sockets[1], **self._sslargs)

    def start_handshake(self, callback=None):
        """Start the SSL handshake. Return a list of ssldata."""
        if self._state != self.s_unwrapped:
            raise RuntimeError('illegal state: {0}'.format(self._state))
        self._create_sslsock()
        self._state = self.s_handshake
        self._handshake_callback = callback
        ssldata, appdata = self.feed_ssldata(b'')
        assert len(appdata) == 0
        return ssldata

    def start_shutdown(self, callback=None):
        """Start the SSL shutdown sequence. Return a list of ssldata."""
        if self._state != self.s_wrapped:
            raise RuntimeError('illegal state: {0}'.format(self._state))
        self._state = self.s_shutdown
        self._shutdown_callback = callback
        ssldata, appdata = self.feed_ssldata(b'')
        assert len(appdata) == 0
        return ssldata

    def feed_ssldata(self, data):
        """Feed SSL level data into the pipe.
        
        Return a (ssldata, appdata) tuple. The ssldata element is a list of
        buffers containing SSL data that needs to be sent to the remote SSL
        instance. The appdata element is a list of buffers containing
        application data that needs to be forwarded to the application.

        For performance it is best to pass *data* as a memoryview. This
        prevents the copying of data in case of short writes.
        """
        if self._state == self.s_unwrapped:
            return ([], [data] if data else [])
        offset = 0
        ssldata = []; appdata = []
        while True:
            nbytes = write_to_socket(self._sockets[0], data[offset:])
            offset += nbytes
            try:
                if self._state == self.s_handshake:
                    self._sslsock.do_handshake()
                    self._state = self.s_wrapped
                    if self._handshake_callback:
                        self._handshake_callback()
                if self._state == self.s_wrapped:
                    while True:
                        chunk = self._sslsock.read(self.bufsize)
                        if not chunk:
                            # clean shutdown: automatically acknowledge below
                            # Automatic aknowledging has an issue. It changes
                            # state of _sslsock before the read callback has
                            # been called. So it may be called with a previous
                            # ssl state.
                            self._state = self.s_shutdown
                            break
                        appdata.append(chunk)
                if self._state == self.s_shutdown:
                    unwrapped = self._sslsock.unwrap()
                    if hasattr(socket, '_socketobject'):
                        # Python 2.7
                        unwrapped = socket._socketobject(_sock=unwrapped)
                    self._sockets = (self._sockets[0], unwrapped)
                    self._state = self.s_unwrapped
                    self._sslsock = None
                    if self._shutdown_callback:
                        self._shutdown_callback()
                if self._state == self.s_unwrapped:
                    # Drain the socket pair from any left-over clear-text
                    # data from after the SSL shutdown.
                    chunks = read_from_socket(self._sockets[1], self.bufsize)
                    appdata.extend(chunks)
            except ssl.SSLError as e:
                if e.args[0] not in ssl_error_nb:
                    raise
            # Check for record level data that needs to be sent
            # back. Happens for the initial handshake and renegotiations.
            chunks = read_from_socket(self._sockets[0], self.bufsize)
            ssldata.extend(chunks)
            if offset == len(data):
                break
        return (ssldata, appdata)

    def feed_appdata(self, data, offset=0):
        """Feed SSL application level data into the pipe.

        Return a tuple (ssldata, offset) tuple. The ssldata element is a list
        of buffers containing SSL data that needs to be sent to the remote SSL
        instance. The offset element is the number of bytes sent. It may be
        less than the length of data. In the latter case, more ssl level data
        needs to be provided via :meth:`feed_ssldata` to complete a handshake.

        For performance it is best to pass *data* as a memoryview. This
        prevents the copying of data in case of short writes.

        NOTE: In case of short writes, this call MUST be retried with the SAME
        buffer passed into the *data* argument (i.e. the ``id()`` must be the
        same). This is an OpenSSL requirement.
        """
        if self._state == self.s_unwrapped:
            return ([data], len(data))
        elif self._state in (self.s_handshake, self.s_shutdown):
            # handshake in progress, caller cannot write app data now.
            return ([], 0)
        ssldata = []
        while True:
            # See if we need to retry a previous short write.
            if self._fragment:
                fragment = self._fragment
                self._fragment = None
            else:
                fragment = data[offset:]
            # Short writes happen a lot since the _ssl module does not enable
            # partial writes.
            try:
                nbytes = self._sslsock.write(fragment)
                offset += nbytes
            except ssl.SSLError as e:
                if e.args[0] == ssl.SSL_ERROR_WANT_READ:
                    # We need to return a short write here to our caller here..
                    # The SSL socket needs more input, likely a renegotiation.
                    self._fragment = fragment
                elif e.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                    # The output buffer is full. We empty it below.
                    pass
                else:
                    raise
            # See if there's any record level data back for us.
            chunks = read_from_socket(self._sockets[0], self.bufsize)
            ssldata.extend(chunks)
            if self._fragment or offset == len(data):
                break
        return (ssldata, offset)


class SSL(pyuv.TCP):
    """An SSL/TLS transport."""

    def __init__(self, context=None, **sslargs):
        """The *context* argument may be used to specify the
        :class:`ssl.SSLContext` to use. Note that SSL contexts were first
        introduced in Python 3.2 and so on Python 2.x you cannot use this
        argument.

        The *sslargs* keyword arguments may be used to specify any arguments
        that are valid for :func:`ssl.wrap_socket`.

        This class inherits from :class:`pyuv.TCP` and implements the same
        interface. In addition to the methods provided by its base class, the
        following methods are available:
        """
        super(SSL, self).__init__(get_hub().loop)
        self._context = context
        self._sslargs = sslargs
        self._sslpipe = SSLPipe(self._context, **self._sslargs)
        self._server_side = self._sslargs.get('server_side')
        self._do_handshake_on_connect = \
                    self._sslargs.get('do_handshake_on_connect', True)
        self._read_callback = None
        self._read_handshake = False
        self._reading = False
        # Note: the read and write backlog contain application level data
        # There is no backlog on the SSL side.
        self._read_backlog = collections.deque()
        self._write_backlog = collections.deque()

    def write(self, data, callback=None):
        self._write_backlog.append((data, 0, callback))
        self._write()

    def _write(self):
        # Try to make progress on the write backlog.
        while self._write_backlog:
            data, offset, callback = self._write_backlog.popleft()
            ssldata, offset = self._sslpipe.feed_appdata(data, offset)
            if ssldata:
                for chunk in ssldata[:-1]:
                    super(SSL, self).write(chunk)
                # The user provided callback piggies back on the last chunk
                super(SSL, self).write(ssldata[-1], callback)
            if offset != len(data):
                # A short write implies that a write is blocked on a read that
                # is needed for a renegotiation. We cannot make progress until
                # we get more data in _on_transport_readable() below.
                self._write_backlog.appendleft((data, offset, callback))
                break

    def _read(self):
        # Try to make progress on the read backlog.
        if not self._read_callback:
            return
        while self._read_backlog:
            transport, data, error = self._read_backlog.popleft()
            self._read_callback(transport, data, error)

    def _on_transport_readable(self, transport, data, error):
        if error:
            assert data is None
            self._read_backlog.append((transport, data, error))
        else:
            ssldata, appdata = self._sslpipe.feed_ssldata(data)
            for chunk in ssldata:
                super(SSL, self).write(chunk)
            for chunk in appdata:
                self._read_backlog.append((transport, chunk, error))
        self._read()
        self._write()

    def _start_stop_reading(self):
        if self._read_handshake or self._read_callback:
            if not self._reading:
                super(SSL, self).start_read(self._on_transport_readable)
                self._reading = True
        else:
            super(SSL, self).stop_read()
            self._reading = False

    def start_read(self, callback):
        # Server-side initialization is done on the first start_read() call.
        # Ideally, this would be done in accept(). However there is no way to
        # hook that, as the server is accept()ing directly into us by poking
        # into the C-level structure below us.
        if self._server_side is None:
            # I've been bitten by this...
            raise RuntimeError('Need to specify server_side=True for a server socket.')
        if self._server_side and self._do_handshake_on_connect:
            self.do_handshake()
        self._read_callback = callback
        self._start_stop_reading()
        # If there was a backlog clear it out now.
        self._read()

    def stop_read(self):
        self._read_callback = None
        self._start_stop_reading()

    def connect(self, addr, callback=None):
        self._server_side = False
        def on_connect_complete(transport, error):
            if error or not self._do_handshake_on_connect:
                if callback:
                    callback(transport, error)
            elif self._do_handshake_on_connect:
                self.do_handshake((lambda h,e: callback(transport, error))
                                        if callback else None)
        super(SSL, self).connect(addr, on_connect_complete)

    def close(self, callback=None):
        if self._sslpipe.state == SSLPipe.s_unwrapped:
            super(SSL, self).close(callback)
        else:
            self.unwrap(lambda h,e: super(SSL, self).close(callback))

    def do_handshake(self, callback=None):
        """Start the SSL handshake.

        The *callback*, if specified, will be called when the handshake
        completes. The callback signature is: ``callback(transport, error)``.
        """
        # If we are not reading, we temporarily enable it. Otherwise the
        # handshake would not complete. Note: this may accumulate application
        # level data in the read backlog. That will be cleared when reading
        # will be next enabled.
        def on_handshake_complete():
            self._read_handshake = False
            self._start_stop_reading()
            if callback:
                callback(self, 0)
        ssldata = self._sslpipe.start_handshake(on_handshake_complete)
        for chunk in ssldata:
            super(SSL, self).write(chunk)
        self._read_handshake = True
        self._start_stop_reading()

    def unwrap(self, callback=None):
        """Start the SSL shutdown handshake.

        The *callback*, if specified, will be called when the handshake
        completes. The callback signature is: ``callback(transport, error)``.
        """
        # See note in do_handshake() on why reading is enabled.
        def on_unwrap_complete():
            self._read_handshake = False
            self._start_stop_reading()
            if callback:
                callback(self, 0)
        ssldata = self._sslpipe.start_shutdown(on_unwrap_complete)
        for chunk in ssldata:
            super(SSL, self).write(chunk)
        self._read_handshake = True
        self._start_stop_reading()

    @property
    def ssl(self):
        """The internal :class:`ssl.SSLSocket` used by the transport.
        
        See `ssl.SSLSocket
        <http://docs.python.org/3/library/ssl.html#ssl-sockets>`_ for an API
        reference.  Acessing the SSL socket is useful for getting information
        on the SSL state such as the active encryption algorithm, compression
        method, etc. You should not call any method on this object that can
        modify its state.
        """
        return self._sslpipe.socket
