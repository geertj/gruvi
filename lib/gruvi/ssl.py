#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
import ssl

from . import compat
from .transports import Transport, TransportError
from .sync import Event

from .sslcompat import SSLContext, MemoryBIO, get_reason, wrap_bio

__all__ = ['SslTransport', 'create_ssl_context']


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

    # This previously used a socketpair to communicate with the SSL protocol
    # instance but since October 2014 we're using a Memory BIO! This is
    # cleaner, and more reliable on Windows. See for example issue #12 for more
    # details.

    S_UNWRAPPED, S_DO_HANDSHAKE, S_WRAPPED, S_SHUTDOWN = range(4)

    def __init__(self, context, server_side, server_hostname=None):
        """
        The *context* argument specifies the :class:`ssl.SSLContext` to use.
        It is recommended to use :func:`~gruvi.ssl.create_ssl_context` so that
        it will work on all supported Python versions.

        The *server_side* argument indicates whether this is a server side or
        client side transport.

        The optional *server_hostname* argument can be used to specify the
        hostname you are connecting to. You may only specify this parameter if
        the _ssl module supports Server Name Indication (SNI).
        """
        self._context = context
        self._server_side = server_side
        self._server_hostname = server_hostname
        self._state = self.S_UNWRAPPED
        self._bios = (MemoryBIO(), MemoryBIO())
        self._sslobj = None
        self._need_ssldata = False

    @property
    def context(self):
        """The SSL context passed to the constructor."""
        return self._context

    @property
    def ssl(self):
        """The internal :class:`ssl.SSLObject` instance."""
        return self._sslobj

    @property
    def need_ssldata(self):
        """Whether more record level data is needed to complete a handshake
        that is currently in progress."""
        return self._need_ssldata

    @property
    def wrapped(self):
        """Whether a security layer is currently in effect."""
        return self._state == self.S_WRAPPED

    def do_handshake(self, callback=None):
        """Start the SSL handshake. Return a list of ssldata.

        The optional *callback* argument can be used to install a callback that
        will be called when the handshake is complete. The callback will be
        called without arguments.
        """
        if self._state != self.S_UNWRAPPED:
            raise RuntimeError('handshake in progress or completed')
        wrapargs = (self._bios[0], self._bios[1], self._server_side, self._server_hostname)
        self._sslobj = wrap_bio(self._context, *wrapargs)
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
        if self._state == self.S_UNWRAPPED:
            raise RuntimeError('no security layer present')
        self._state = self.S_SHUTDOWN
        self._on_handshake_complete = callback
        ssldata, appdata = self.feed_ssldata(b'')
        assert appdata == [] or appdata == [b'']
        return ssldata

    def feed_eof(self):
        """Send a potentially "ragged" EOF.

        This method will raise an SSL_ERROR_EOF exception if the EOF is
        unexpected.
        """
        self._bios[0].write_eof()
        ssldata, appdata = self.feed_ssldata(b'')
        assert appdata == [] or appdata == [b'']

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
        if self._state == self.S_UNWRAPPED:
            # If unwrapped, pass plaintext data straight through.
            return ([], [data] if data else [])
        ssldata = []; appdata = []
        self._need_ssldata = False
        if data:
            self._bios[0].write(data)
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
                self._sslobj.unwrap()
                self._sslobj = None
                self._state = self.S_UNWRAPPED
                if self._on_handshake_complete:
                    self._on_handshake_complete()
            if self._state == self.S_UNWRAPPED:
                # Drain possible plaintext data after close_notify.
                appdata.append(self._bios[0].read())
        except ssl.SSLError as e:
            if e.errno not in (ssl.SSL_ERROR_WANT_READ, ssl.SSL_ERROR_WANT_WRITE,
                               ssl.SSL_ERROR_SYSCALL):
                raise
            self._need_ssldata = e.errno == ssl.SSL_ERROR_WANT_READ
        # Check for record level data that needs to be sent back.
        # Happens for the initial handshake and renegotiations.
        if self._bios[1].pending:
            ssldata.append(self._bios[1].read())
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
        view = memoryview(data)
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
                if e.errno not in (ssl.SSL_ERROR_WANT_READ, ssl.SSL_ERROR_WANT_WRITE,
                                   ssl.SSL_ERROR_SYSCALL):
                    raise
                self._need_ssldata = e.errno == ssl.SSL_ERROR_WANT_READ
            # See if there's any record level data back for us.
            if self._bios[1].pending:
                ssldata.append(self._bios[1].read())
            if offset == len(view) or self._need_ssldata:
                break
        return (ssldata, offset)


class SslTransport(Transport):
    """An SSL/TLS transport."""

    def __init__(self, handle, context, server_side, server_hostname=None,
                 do_handshake_on_connect=True, close_on_unwrap=True):
        """
        The *handle* argument is the pyuv handle on top of which to layer the
        SSL transport. It must be a ``pyuv.Stream`` instance, so either a
        :class:`pyuv.TCP`, :class:`pyuv.Pipe` or a :class:`pyuv.TTY`.

        SSL transports are always read-write, so the handle provided needs
        to support that.

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
        ``'ssl'``               The internal ``ssl.SSLObject`` instance used by
                                this transport.
        ``'sslctx'``            The ``ssl.SSLContext`` instance used to create
                                the SSL object.
        ======================  ===============================================
        """
        if name == 'ssl':
            return self._sslpipe.ssl
        elif name == 'sslctx':
            return self._sslpipe.context
        else:
            return super(SslTransport, self).get_extra_info(name, default)

    def write(self, data):
        # Write *data* to the transport.
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data: expecting a bytes-like instance, got {!r}"
                                .format(type(data).__name__))
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._closing or self._handle.closed:
            raise TransportError('transport is closing/closed')
        elif len(data) == 0:
            return
        self._write_backlog.append([data, 0])
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
                # Temporarily set _closing to False to prevent Transport.write()
                # from raising an error when we are doing a close_notify.
                saved, self._closing = self._closing, False
                # Write the ssl data that came out of the SSL pipe to the handle.
                # Note that flow control is done at the record level data.
                for chunk in ssldata:
                    super(SslTransport, self).write(chunk)
                self._closing = saved
                if offset < len(data):
                    self._write_backlog[0][1] = offset
                    # A short write means that a write is blocked on a read
                    # We need to enable reading if it is not enabled!!
                    # At the same time stop the protocol from writing data to
                    # make the situation not worse.
                    assert self._sslpipe.need_ssldata
                    if not self._reading:
                        self.resume_reading()
                    if self._writing:
                        self._protocol.pause_writing()
                        self._writing = False
                    break
                # An entire chunk from the backlog was processed. We can
                # delete it and reduce the outstanding buffer size.
                del self._write_backlog[0]
        except ssl.SSLError as e:
            self._log.warning('SSL error {} (reason {})', e.errno, e.reason, exc_info=True)
            self._error = e
            self.abort()

    def _on_read_complete(self, handle, data, error):
        # Callback used with handle.start_read().
        assert handle is self._handle
        try:
            if self._error:
                self._log.warning('ignore read status {} after close', error)
            elif error == pyuv.errno.UV_EOF:
                self._sslpipe.feed_eof()  # Raises SSL_ERROR_EOF if unexpected
                if self._protocol.eof_received() and not self._close_on_unwrap:
                    self._log.debug('EOF received, protocol wants to continue')
                elif not self._closing:
                    self._log.debug('EOF received, closing transport')
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
                        # close_notify
                        self.close()
        except ssl.SSLError as e:
            self._log.warning('SSL error {} (reason {})', e.errno,
                              getattr(e, 'reason', 'unknown'), exc_info=True)
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
        callback even if it called :meth:`pause_reading` before.
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
        self._process_write_backlog()

    def can_write_eof(self):
        # SSL/TLS does not support a half close. Theoretically we could return
        # True here when unwrapped.
        return False

    def close(self):
        """Cleanly shut down the SSL protocol and close the transport."""
        if self._closing or self._handle.closed:
            return
        self._closing = True
        self._write_backlog.append([b'', False])
        self._process_write_backlog()


def create_ssl_context(**sslargs):
    """Create a new SSL context in a way that is compatible with different
    Python versions."""
    context = SSLContext(ssl.PROTOCOL_SSLv23)
    if sslargs.get('certfile'):
        context.load_cert_chain(sslargs['certfile'], sslargs.get('keyfile'))
    if sslargs.get('ca_certs'):
        context.load_verify_locations(sslargs['ca_certs'])
    if sslargs.get('cert_reqs'):
        context.verify_mode = sslargs['cert_reqs']
    if sslargs.get('ciphers'):
        context.set_ciphers(sslargs['ciphers'])
    return context
