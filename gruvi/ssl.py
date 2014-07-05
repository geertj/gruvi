#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import errno
import socket
import io
import pyuv
import ssl
import six

from . import compat
from .transports import Transport, TransportError
from .sync import Event

if hasattr(socket, 'socketpair'):
    socketpair = socket.socketpair
else:
    from .socketpair import socketpair

if six.PY2:
    from . import sslcompat
    HAVE_SSL_BACKPORTS = sslcompat._sslcompat is not None
else:
    HAVE_SSL_BACKPORTS = False

__all__ = ['SslTransport', 'create_ssl_context', 'HAVE_SSL_BACKPORTS']


def write_to_socket(sock, data):
    """Write as much of *data* to the socket as possible, retrying short writes
    due to EINTR only."""
    offset = 0
    while offset != len(data):
        try:
            nbytes = sock.send(data[offset:])
        except (io.BlockingIOError, socket.error) as e:
            if e.errno == errno.EINTR:
                continue
            elif e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
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
            if e.errno == errno.EINTR:
                continue
            elif e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                break
            raise
        chunks.append(chunk)
    return chunks


def get_reason(exc):
    """Return the reason code from an SSLError exception."""
    # On Python 3.x the reason is available via exc.reason.
    if hasattr(exc, 'reason'):
        return exc.reason
    # .. but on 2.x we have to parse the error string (fortunately it is there)
    message = exc.args[1]
    p0 = message.find('error:')
    if p0 == -1:
        return
    p0 += 6
    p1 = message.find(':', p0)
    assert p1 != -1
    code = int(message[p0:p1], 16) & 0xfff
    return sslcompat.errorcode.get(code)


class SslPipe(object):
    """An SSL "Pipe".

    An SSL pipe allows you to communicate with an SSL/TLS protocol instance
    through memory buffers. It can be used to implement a security layer for an
    existing connection where you don't have access to the connection's file
    descriptor, or for some reason you don't want to use it.

    An SSL pipe can be in "wrapped" and "unwrapped" mode. In unwrapped mode,
    data is passed through untransformed. In wrapped mode, application level
    data is encrypted to SSL record level data and vice versa. The SSL record
    level is the lowest level in the SSL protocol suite and is what travels
    as-is over the wire.

    An SslPipe initially is in "unwrapped" mode. To start SSL, call
    :meth:`do_handshake`. To shutdown SSL again, call :meth:`unwrap`.
    """

    bufsize = 65536

    # This class uses a socket pair to communicate with the SSL protocol
    # instance. A "Memory BIO" would hav been more efficient, however the _ssl
    # module doesn't support that (as of March 2014 / Python 3.4). See alo:
    # http://mail.python.org/pipermail/python-ideas/2012-November/017686.html

    S_UNWRAPPED, S_DO_HANDSHAKE, S_WRAPPED, S_SHUTDOWN = range(4)

    def __init__(self, context, server_side, server_hostname=None):
        """
        The *context* argument specifies the :class:`ssl.SSLContext` to use.
        In Python 2.x this class isn't available and you can use
        :class:`sslcompat.SSLContext` instead.

        The *server_side* argument indicates whether this is a server side or
        client side socket.

        The optional *server_hostname* argument can be used to specify the
        hostname you are connecting to. You may only specify this parameter if
        the _ssl module supports Server Name Indication (SNI).
        """
        self._context = context
        self._server_side = server_side
        self._server_hostname = server_hostname
        self._state = self.S_UNWRAPPED
        self._sockets = socketpair()
        for sock in self._sockets:
            sock.setblocking(False)
        self._sslobj = None
        self._sslinfo = None
        self._need_ssldata = False

    @property
    def sslsocket(self):
        """The raw ``_ssl._SSLSocket`` instance."""
        return self._sslobj

    @property
    def sslcontext(self):
        """The raw ``_ssl._SSLContext`` instance."""
        return self._context

    @property
    def need_ssldata(self):
        """Whether more record level data is needed to complete a handshake
        that is currently in progress."""
        return self._need_ssldata

    def do_handshake(self, callback=None):
        """Start the SSL handshake. Return a list of ssldata.

        The optional *callback* argument can be used to install a callback that
        will be called when the handshake is complete. The callback will be
        called without arguments.
        """
        if self._sockets is None:
            raise RuntimeError('pipe was closed')
        if self._sslobj:
            raise RuntimeError('handshake in progress or completed')
        self._sslobj = self._context._wrap_socket(self._sockets[1], self._server_side,
                                                  self._server_hostname)
        self._state = self.S_DO_HANDSHAKE
        self._on_handshake_complete = callback
        ssldata, appdata = self.feed_ssldata(b'')
        assert len(appdata) == 0
        return ssldata

    def shutdown(self, callback=None):
        """Start the SSL shutdown sequence. Return a list of ssldata.

        The optional *callback* argument can be used to install a callback that
        will be called when the shutdown is complete. The callback will be
        called without arguments.
        """
        if self._sockets is None:
            raise RuntimeError('pipe was closed')
        if self._sslobj is None:
            raise RuntimeError('no security layer present')
        self._state = self.S_SHUTDOWN
        self._on_handshake_complete = callback
        ssldata, appdata = self.feed_ssldata(b'')
        assert len(appdata) == 0
        return ssldata

    def feed_eof(self):
        """Send a potentially "ragged" EOF.

        This method will raise an SSL_ERROR_EOF exception if the EOF is
        unexpected.
        """
        if self._sockets is None:
            raise RuntimeError('pipe was closed')
        try:
            self._sockets[0].shutdown(socket.SHUT_WR)
            ssldata, appdata = self.feed_ssldata(b'')
        finally:
            self.close()
        assert len(ssldata) == 0
        assert appdata == []

    def close(self):
        """Close the SSL pipe."""
        if self._sockets is None:
            return
        self._sslobj = None
        self._sslinfo = None
        for sock in self._sockets:
            sock.close()
        self._sockets = None

    def feed_ssldata(self, data):
        """Feed SSL record level data into the pipe.

        The data must be a bytes instance. It is OK to send an empty bytes
        instance. This can be used to get ssldata for a handshake initiated by
        this endpoint.

        Return a (ssldata, appdata) tuple. The ssldata element is a list of
        buffers containing SSL data that needs to be sent to the remote SSL.

        The appdata element is a list of buffers containing plaintext data that
        needs to be forwarded to the application. The appdata list may contain
        an empty buffer indicating an SSL "close_notify" alert. This alert must
        be acknowledged by calling :meth:`shutdown`.
        """
        if self._sockets is None:
            raise RuntimeError('pipe was closed')
        if self._state == self.S_UNWRAPPED:
            # If unwrapped, pass plaintext data straight through.
            return ([], [data] if data else [])
        view = compat.memoryview(data)
        offset = 0
        ssldata = []; appdata = []
        while True:
            self._need_ssldata = False
            offset += write_to_socket(self._sockets[0], view[offset:])
            try:
                if self._state == self.S_DO_HANDSHAKE:
                    # Call do_handshake() until it doesn't raise anymore.
                    self._sslobj.do_handshake()
                    self._state = self.S_WRAPPED
                    if self._on_handshake_complete:
                        self._on_handshake_complete()
                if self._state == self.S_WRAPPED:
                    # Main state: read data from SSL until close_notify
                    while True:
                        chunk = self._sslobj.read(self.bufsize)
                        appdata.append(chunk)
                        if not chunk:  # close_notify
                            break
                if self._state == self.S_SHUTDOWN:
                    # Call shutdown() until it doesn't raise anymore.
                    self._sslobj.shutdown()
                    self._sslobj = None
                    self._state = self.S_UNWRAPPED
                    if self._on_handshake_complete:
                        self._on_handshake_complete()
                if self._state == self.S_UNWRAPPED:
                    # Drain possible plaintext data after close_notify.
                    chunks = read_from_socket(self._sockets[1], self.bufsize)
                    appdata.extend(chunks)
            except ssl.SSLError as e:
                if e.errno not in (ssl.SSL_ERROR_WANT_READ, ssl.SSL_ERROR_WANT_WRITE):
                    raise
                self._need_ssldata = e.errno == ssl.SSL_ERROR_WANT_READ
            # Check for record level data that needs to be sent back.
            # Happens for the initial handshake and renegotiations.
            chunks = read_from_socket(self._sockets[0], self.bufsize)
            ssldata.extend(chunks)
            # We are done if we wrote all data.
            if offset == len(view):
                break
        return (ssldata, appdata)

    def feed_appdata(self, data, offset=0):
        """Feed plaintext data into the pipe.

        Return an (ssldata, offset) tuple. The ssldata element is a list of
        buffers containing record level data that needs to be sent to the
        remote SSL instance. The offset is the number of plaintext bytes that
        were processed, which may be less than the length of data.

        NOTE: In case of short writes, this call MUST be retried with the SAME
        buffer passed into the *data* argument (i.e. the ``id()`` must be the
        same). This is an OpenSSL requirement. A further particularity is that
        a short write will always have offset == 0, because the _ssl module
        does not enable partial writes. And even though the offset is zero,
        there will still be encrypted data in ssldata.
        """
        if self._state == self.S_UNWRAPPED:
            # pass through data in unwrapped mode
            return ([data[offset:]] if offset < len(data) else [], len(data))
        ssldata = []
        view = compat.memoryview(data)
        while True:
            self._need_ssldata = False
            try:
                if offset < len(view):
                    offset += self._sslobj.write(view[offset:])
            except ssl.SSLError as e:
                # It is not allowed to call write() after unwrap() until the
                # close_notify is acknowledged. We return the condition to the
                # caller as a short write.
                if get_reason(e) == 'PROTOCOL_IS_SHUTDOWN':
                    e.errno = ssl.SSL_ERROR_WANT_READ
                if e.errno not in (ssl.SSL_ERROR_WANT_READ, ssl.SSL_ERROR_WANT_WRITE):
                    raise
                self._need_ssldata = e.errno == ssl.SSL_ERROR_WANT_READ
            # See if there's any record level data back for us.
            chunks = read_from_socket(self._sockets[0], self.bufsize)
            ssldata.extend(chunks)
            if offset >= len(view) or self._need_ssldata:
                break
        return (ssldata, offset)


class SslTransport(Transport):
    """An SSL/TLS transport."""

    def __init__(self, handle, context, server_side, server_hostname=None,
                 do_handshake_on_connect=True, close_on_unwrap=True):
        """
        The *context* argument specifies the :class:`ssl.SSLContext` to use.
        You can use :func:`create_ssl_context` to create a new context which
        also works on Python 2.x where :class:`ssl.SSLContext` does not exist.

        The *server_side* argument specifies whether this is a server side or a
        client side transport.

        The optional *server_hostname* argument can be used to specify the
        hostname you are connecting to. You may only specify this parameter if
        your Python version supports SNI.

        The optional *do_handshake_on_connect* argument specifies whether to to
        start the SSL handshake immediately. If False, then the connection will
        be unencrypted until :meth:`do_handshake` is called. The default is to
        start the handshake immediately.

        The optional *close_on_unwrap* argument specifies whether you want the
        ability to continue using the connection after you call :meth:`unwrap`
        of when an SSL "close_notify" is received from the remote peer. The
        default is to close the connection.
        """
        super(SslTransport, self).__init__(handle)
        self._sslpipe = SslPipe(context, server_side, server_hostname)
        self._do_handshake_on_connect = do_handshake_on_connect
        self._close_on_unwrap = close_on_unwrap
        self._write_backlog = []
        self._ssl_active = Event()

    def start(self, protocol):
        # Bind to *protocol* and start calling callbacks on it.
        events = super(SslTransport, self).start(protocol)
        if self._do_handshake_on_connect:
            self.do_handshake()
            if events is None:
                events = []
            events.append(self._ssl_active)
        return events

    def get_extra_info(self, name, default=None):
        """Return transport specific data.

        The following fields are available, in addition to the information
        exposed by :meth:`Transport.get_extra_info`.

        ======================  ===============================================
        Name                    Description
        ======================  ===============================================
        ``'compression'``       The compression algorithm being used, or `None`
                                if the connection is not compressed. See
                                :meth:`ssl.SSLSocket.compression`.
        ``'cipher'``            A 3-tuple ``(name, version, bits)`` describing
                                the cipher currently in use, or `None` if no
                                cipher is currently in effect. See
                                :meth:`ssl.SSLSocket.cipher`.
        ``'peercert'``          The peer certificate. See
                                :meth:`.ssl.SSLSocket.getpeercert`.
        ``'tls_unique_cb'``     The tls-unique channel bindings, or None if no
                                channel bindings are available.
        ``'sslsocket'``         The internal ``_ssl._SSLSocket`` instance
                                used by this transport.
        ``'sslcontext'``        The internal ``_ssl._SSLContext`` instance
                                used by this transport.
        ======================  ===============================================
        """
        sslsock = self._sslpipe.sslsocket
        sslctx = self._sslpipe.sslcontext
        if sslsock is None:
            return super(SslTransport, self).get_extra_info(name, default)
        if name == 'compression':
            if hasattr(sslsock, 'compression'):
                return sslsock.compression()
            elif HAVE_SSL_BACKPORTS:
                return sslcompat.compression(sslsock)
            else:
                return default
        elif name == 'cipher':
            return sslsock.cipher()
        elif name == 'peercert':
            return sslsock.peer_certificate(False)
        elif name == 'tls_unique_cb':
            if hasattr(sslsock, 'tls_unique_cb'):
                return sslsock.tls_unique_cb()
            elif HAVE_SSL_BACKPORTS:
                return sslcompat.tls_unique_cb(sslsock)
            else:
                return default
        elif name == 'sslsocket':
            return sslsock
        elif name == 'sslcontext':
            return sslctx
        else:
            return super(SslTransport, self).get_extra_info(name, default)

    def _on_close_complete(self, handle):
        # Callback used with handle.close() in BaseTransport
        super(SslTransport, self)._on_close_complete(handle)
        self._sslpipe.close()
        self._sslpipe = None

    def write(self, data):
        # Write *data* to the transport.
        if not isinstance(data, (bytes, bytearray, compat.memoryview)):
            raise TypeError("data: expecting a bytes-like instance, got {0!r}"
                                .format(type(data).__name__))
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._closing or self._handle.closed:
            raise TransportError('transport is closing/closed')
        elif len(data) == 0:
            return
        self._write_backlog.append([data, 0])
        self._write_buffer_size += len(data)
        if self._write_buffer_size >= self._write_buffer_high and self._writing:
            self._writing = False
            self._protocol.pause_writing()
        self._process_write_backlog()

    def _process_write_backlog(self):
        # Try to make progress on the write backlog.
        try:
            for i in range(len(self._write_backlog)):
                data, offset = self._write_backlog[0]
                if data:
                    ssldata, offset = self._sslpipe.feed_appdata(data, offset)
                elif offset:
                    ssldata, offset = self._sslpipe.do_handshake(self._ssl_active.set), 1
                else:
                    ssldata, offset = self._sslpipe.shutdown(self._ssl_active.clear), 1
                # Temporarily set _closing to False to prevent
                # Transport.write() from raising an error.
                saved, self._closing = self._closing, False
                for chunk in ssldata:
                    super(SslTransport, self).write(chunk)
                self._closing = saved
                if offset < len(data):
                    self._write_backlog[0][1] = offset
                    # A short write means that a write is blocked on a read
                    # We need to enable reading if it is not enabled!!
                    assert self._sslpipe.need_ssldata
                    if not self._reading:
                        self.resume_reading()
                    break
                # An entire chunk from the backlog was processed. We can
                # delete it and reduce the outstanding buffer size.
                del self._write_backlog[0]
                self._write_buffer_size -= offset
        except ssl.SSLError as e:
            self._log.warning('SSL error {} (reason {})', e.errno, e.reason)
            self._error = e
            self.abort()

    def _read_callback(self, handle, data, error):
        # Callback used with handle.start_read().
        assert handle is self._handle
        try:
            if self._error:
                self._log.warning('ignore read status {} after close', error)
            elif error == pyuv.errno.UV_EOF:
                self._sslpipe.feed_eof()  # Raises SSL_ERROR_EOF if unexpected
                if not self._close_on_unwrap and self._protocol.eof_received():
                    self._log.debug('EOF received, protocol wants to continue')
                elif not self._closing:
                    self._log.debug('EOF received, closing transport')
                    self._error = TransportError('connection lost')
                    super(SslTransport, self).close()
            elif error:
                self._log.warning('pyuv error {} in read callback', error)
                self._error = TransportError.from_errno(error)
                self.abort()
            else:
                ssldata, appdata = self._sslpipe.feed_ssldata(data)
                for chunk in ssldata:
                    super(SslTransport, self).write(chunk)
                for chunk in appdata:
                    if chunk and not self._closing:
                        self._protocol.data_received(chunk)
                    elif not chunk and self._close_on_unwrap:
                        self.close()
        except ssl.SSLError as e:
            self._log.warning('SSL error {} (reason {})', e.errno, e.reason)
            self._error = e
            self.abort()
        # Process write backlog. A read could have unblocked a write.
        if not self._error:
            self._process_write_backlog()

    def pause_reading(self):
        """Stop reading data.

        Flow control for SSL is a little bit more complicated than for a
        regular :class:`Transport` because SSL handshakes can occur at any time
        during a connection. These handshakes require reading to be enabled,
        even if the application called :meth:`pause_reading` before.

        The approach taken by Gruvi is that when a handshake occurs, reading is
        always enabled even if :meth:`pause_reading` was called before. I
        believe this is the best way to prevent complex read side buffering
        that could also result in read buffers of arbitrary size.

        The consequence is that if you are implementing your own protocol and
        you want to support SSL, then your protocol should be able to handle a
        callback even if it called :meth:`pause_reading` before. The
        recommended way to do this is to store a flag "currently reading" and
        set it when you call :meth:`resume_reading` and when
        :meth:`Protocol.data_received` is called by the transport. Based on
        this flag you can prevent calling :meth:`resume_reading` when you are
        already reading due to a handshake.
        """
        if self._sslpipe.need_ssldata:
            return
        super(SslTransport, self).pause_reading()

    def resume_reading(self):
        """Resume reading data.

        See the note in :meth:`pause_reading` for special considerations on
        flow control with SSL.
        """
        return super(SslTransport, self).resume_reading()

    def do_handshake(self):
        """Start the SSL handshake.

        This method only needs to be called if this transport was created with
        *do_handshake_on_connect* set to False (the default is True).

        The handshake needs to be synchronized between the both endpoints, so
        that SSL record level data is not incidentially interpreted as
        plaintext. Usually this is done by starting the handshake directly
        after a connection is established, but you can also use an application
        level protocol.
        """
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._closing or self._handle.closed:
            raise TransportError('SSL transport is closing/closed')
        self._write_backlog.append([b'', True])
        self._write_buffer_size += 1
        self._process_write_backlog()

    def unwrap(self):
        """Remove the security layer.

        Use this method only if you want to send plaintext data on the
        connection after the security layer has been removed. In all other
        cases, use :meth:`close`.

        If the unwrap is initiated by us, then any data sent after it will be
        buffered until the corresponding close_notify response is received from
        our peer.

        If the unwrap is initiated by the remote peer, then this method will
        acknowledge it. You need an application level protocol to determine
        when to do this because the receipt of a close_notify is not
        communicated to the application.
        """
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._closing or self._handle.closed:
            raise TransportError('SSL transport is closing/closed')
        self._close_on_unwrap = False
        self._write_backlog.append([b'', False])
        self._write_buffer_size += 1
        self._process_write_backlog()

    def can_write_eof(self):
        # SSL/TLS does not support a half close. Theoretically we could return
        # True here when unwrapped.
        return False

    def close(self):
        """Cleanly shut down the SSL protocol and close the socket."""
        if self._closing or self._handle.closed:
            return
        self._closing = True
        self._write_backlog.append([b'', False])
        self._write_buffer_size += 1
        self._process_write_backlog()


def create_ssl_context(**sslargs):
    """Create a new SSL context in a way that is compatible with different
    Python versions.

    On Python 2.6 and 2.7, this creates a emulated SSL context. The returned
    object implements the most important parts the :class:`ssl.SSLContext`
    interface and can be used to configure the SSL connection settings.  It is
    not a real context however and does not support such things as a session
    cache. This function works even if :attr:`gruvi.HAVE_SSL_BACKPORTS` is set
    to `False` (but in this case none of the Python 3.x features can be used,
    obviously).

    On Python 3.3, this creates an new context by calling the
    :class:`ssl.SSLContext` constructor.

    On Python 3.4+, this method creates a new context using
    :func:`ssl.create_default_context`.

    The *sslargs* keyword arguments can be used to set the *certfile*,
    *ca_certs*, *cert_reqs* and *ciphers* context options as described for
    :func:`ssl.wrap_socket`.
    """
    version = sslargs.get('ssl_version')
    if hasattr(ssl, 'create_default_context') and version is None:
        # Python 3.4+
        context = ssl.create_default_context()
    elif hasattr(ssl, 'SSLContext'):
        # Python 3.3
        context = ssl.SSLContext(version or ssl.PROTOCOL_SSLv23)
    else:
        # Python 2.6/2.7
        context = sslcompat.SSLContext(version or ssl.PROTOCOL_SSLv23)
    if sslargs.get('certfile'):
        context.load_cert_chain(sslargs['certfile'], sslargs.get('keyfile'))
    if sslargs.get('ca_certs'):
        context.load_verify_locations(sslargs['ca_certs'])
    if sslargs.get('cert_reqs'):
        context.verify_mode = sslargs['cert_reqs']
    if sslargs.get('ciphers'):
        context.set_ciphers(sslargs['ciphers'])
    return context
