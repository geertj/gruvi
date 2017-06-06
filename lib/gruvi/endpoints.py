#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import socket
import functools
import pyuv
import six
import errno

from . import logging
from .hub import get_hub, switchpoint, switch_back
from .sync import Event
from .errors import Timeout
from .transports import TransportError, Transport
from .ssl import SslTransport
from .sslcompat import create_default_context
from .address import getaddrinfo, saddr

__all__ = ['create_connection', 'create_server', 'Endpoint', 'Client', 'Server']


def _use_af_unix(addr):
    """Return whether to open a :class:`pyuv.Pipe` via an AF_UNIX socket."""
    # This is used on Linux only to support abstract sockets.
    if isinstance(addr, six.text_type) and u'\x00' not in addr \
            or isinstance(addr, six.binary_type) and b'\x00' not in addr:
        return False
    return sys.platform in ('linux', 'linux2', 'linux3')

def _af_unix_helper(handle, address, op):
    """Connect or bind a :class:`pyuv.Pipe` to an AF_UNIX socket.

    We use this on Linux to work around the limitation in the libuv API that
    socket names cannot have null bytes in them (required for abstract
    sockets on Linux).
    """
    # Note that on Linux, connect() to an abstract socket never returns EAGAIN.
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        if op == 'connect':
            sock.connect(address)
        elif op == 'bind':
            sock.bind(address)
        fd = os.dup(sock.fileno())
    except IOError as e:
        # Connecting to an AF_UNIX socket never gives EAGAIN on Linux.
        assert e.errno != errno.EAGAIN
        # Convert from Unix errno -> libuv errno via the symbolic error name
        errname = 'UV_{}'.format(errno.errocode.get(e.errno, 'UNKNOWN'))
        errnum = getattr(pyuv.errno, errname, pyuv.errno.UV_UNKNOWN)
        raise pyuv.error.PipeError(errnum, os.strerror(e.errno))
    finally:
        sock.close()
    handle.open(fd)


@switchpoint
def create_connection(protocol_factory, address, ssl=False, server_hostname=None,
                      local_address=None, family=0, flags=0, timeout=None, mode='rw'):
    """Create a new client connection.

    This method creates a new :class:`pyuv.Handle`, connects it to *address*,
    and then waits for the connection to be established. When the connection is
    established, the handle is wrapped in a transport, and a new protocol
    instance is created by calling *protocol_factory*. The protocol is then
    connected to the transport by calling the transport's
    :meth:`~BaseTransport.start` method which in turn calls
    :meth:`~BaseProtocol.connection_made` on the protocol. Finally the results
    are returned as a ``(transport, protocol)`` tuple.

    The address may be either be a string, a (host, port) tuple, a
    ``pyuv.Stream`` handle or a file descriptor:

    * If the address is a string, this method connects to a named pipe using a
      :class:`pyuv.Pipe` handle. The address specifies the pipe name.
    * If the address is a tuple, this method connects to a TCP/IP service using
      a :class:`pyuv.TCP` handle. The first element of the tuple specifies the
      IP address or DNS name, and the second element specifies the port number
      or service name.
    * If the address is a ``pyuv.Stream`` instance, it must be an already
      connected stream.
    * If the address is a file descriptor, then it is attached to a
      :class:`pyuv.TTY` stream if :func:`os.isatty` returns true, or to a
      :class:`pyuv.Pipe` instance otherwise.

    The *ssl* parameter indicates whether an SSL/TLS connection is desired. If
    so then an :class:`ssl.SSLContext` instance is used to wrap the connection
    using the :mod:`ssl` module's asynchronous SSL support. The context is
    created as follows. If *ssl* is an :class:`~ssl.SSLContext` instance, it is
    used directly. If it is a function, it is called with the connection handle
    as an argument and it must return a context . If it is ``True`` then a
    default context is created using :func:`gruvi.create_default_context`. To
    disable SSL (the default), pass ``False``. If SSL is active, the return
    transport will be an :class:`SslTransport` instance, otherwise it will be a
    :class:`Transport` instance.

    The *server_hostname* parameter is only relevant for SSL connections, and
    specifies the server hostname to use with SNI (Server Name Indication). If
    no server hostname is provided, the hostname specified in *address* is
    used, if available.

    The *local_address* keyword argument is relevant only for TCP transports.
    If provided, it specifies the local address to bind to.

    The *family* and *flags* keyword arguments are used to customize address
    resolution for TCP handles as described in :func:`socket.getaddrinfo`.

    The *mode* parameter specifies if the transport should be put in read-only
    (``'r'``), write-only (``'w'``) or read-write (``'rw'``) mode. For TTY
    transports, the mode must be either read-only or write-only. For all other
    transport the mode should usually be read-write.
    """
    hub = get_hub()
    log = logging.get_logger()
    if isinstance(address, (six.binary_type, six.text_type)):
        handle_type = pyuv.Pipe
        addresses = [address]
    elif isinstance(address, tuple):
        handle_type = pyuv.TCP
        result = getaddrinfo(address[0], address[1], family, socket.SOCK_STREAM,
                             socket.IPPROTO_TCP, flags)
        addresses = [res[4] for res in result]
        if server_hostname is None:
            server_hostname = address[0]
            # Python 2.7 annoyingly gives a unicode IP address
            if not isinstance(server_hostname, str):
                server_hostname = server_hostname.encode('ascii')
    elif isinstance(address, int):
        if os.isatty(address):
            if mode not in ('r', 'w'):
                raise ValueError("mode: must be either 'r' or 'w' for tty")
            handle = pyuv.TTY(hub.loop, address, mode == 'r')
        else:
            handle = pyuv.Pipe(hub.loop, True)
            handle.open(address)
        addresses = []; error = None
    elif isinstance(address, pyuv.Stream):
        handle = address
        addresses = []; error = None
    else:
        raise TypeError('expecting a string, tuple, fd, or pyuv.Stream')
    for addr in addresses:
        log.debug('trying address {}', saddr(addr))
        handle = handle_type(hub.loop)
        try:
            error = None
            if handle_type is pyuv.Pipe and _use_af_unix(addr):
                _af_unix_helper(handle, addr, 'connect')
            else:
                with switch_back(timeout) as switcher:
                    handle.connect(addr, switcher)
                    result = hub.switch()
                    _, error = result[0]
        except pyuv.error.UVError as e:
            error = e[0]
        except Timeout:
            error = pyuv.errno.UV_ETIMEDOUT
        if not error:
            break
        handle.close()
        log.warning('connect() failed with error {}', error)
    if error:
        log.warning('all addresses failed')
        raise TransportError.from_errno(error)
    if local_address:
        handle.bind(*local_address)
    protocol = protocol_factory()
    protocol._timeout = timeout
    if ssl:
        context = ssl if hasattr(ssl, 'set_ciphers') else ssl(handle) if callable(ssl) \
                        else create_default_context(False)
        transport = SslTransport(handle, context, False, server_hostname)
    else:
        transport = Transport(handle, server_hostname, mode)
    events = transport.start(protocol)
    if events:
        for event in events:
            event.wait()
        transport._check_status()
    return (transport, protocol)


@switchpoint
def create_server(protocol_factory, address=None, ssl=False, family=0, flags=0,
                  backlog=128):
    """
    Create a new network server.

    This creates one or more :class:`pyuv.Handle` instances bound to *address*,
    puts them in listen mode and starts accepting new connections. For each
    accepted connection, a new transport is created which is connected to a new
    protocol instance obtained by calling *protocol_factory*.

    The *address* argument may be either be a string, a ``(host, port)`` tuple,
    or a ``pyuv.Stream`` handle:

    * If the address is a string, this method creates a new :class:`pyuv.Pipe`
      instance and binds it to *address*.
    * If the address is a tuple, this method creates one or more
      :class:`pyuv.TCP` handles. The first element of the tuple specifies the
      IP address or DNS name, and the second element specifies the port number
      or service name. A transport is created for each resolved address.
    * If the address is a ``pyuv.Stream`` handle, it must already be bound to
      an address.

    The *ssl* parameter indicates whether SSL should be used for accepted
    connections. See :func:`create_connection` for a description.

    The *family* and *flags* keyword arguments are used to customize address
    resolution for TCP handles as described in :func:`socket.getaddrinfo`.

    The *backlog* parameter specifies the listen backlog i.e the maximum
    number of not yet accepted connections to queue.

    The return value is a :class:`Server` instance.
    """
    server = Server(protocol_factory)
    server.listen(address, ssl=ssl, family=family, flags=flags, backlog=backlog)
    return server


class Endpoint(object):
    """A communications endpoint."""

    def __init__(self, protocol_factory, timeout=None):
        """
        The *protocol_factory* argument constructs a new protocol instance.
        Normally you would pass a :class:`~gruvi.Protocol` subclass.

        The *timeout* argument specifies a timeout for various network operations.
        """
        self._protocol_factory = protocol_factory
        self._timeout = timeout
        self._hub = get_hub()
        self._log = logging.get_logger(self)

    @property
    def timeout(self):
        """The network timeout."""
        return self._timeout

    def close(self):
        """Close the endpoint."""
        raise NotImplementedError


class Client(Endpoint):
    """A client endpoint."""

    def __init__(self, protocol_factory, timeout=None):
        super(Client, self).__init__(protocol_factory, timeout=timeout)
        self._transport = None
        self._protocol = None

    @property
    def transport(self):
        """Return the transport, or ``None`` if not connected."""
        return self._transport

    @property
    def protocol(self):
        """Return the protocol, or ``None`` if not connected."""
        return self._protocol

    @switchpoint
    def connect(self, address, **kwargs):
        """Connect to *address* and wait for the connection to be established.

        See :func:`~gruvi.create_connection` for a description of *address*
        and the supported keyword arguments.
        """
        if self._transport:
            raise RuntimeError('already connected')
        kwargs.setdefault('timeout', self._timeout)
        conn = create_connection(self._protocol_factory, address, **kwargs)
        self._transport = conn[0]
        self._transport._log = self._log
        self._protocol = conn[1]
        self._protocol._log = self._log

    @switchpoint
    def close(self):
        """Close the connection."""
        if self._transport is None:
            return
        self._transport.close()
        self._transport._closed.wait()
        self._transport = None
        self._protocol = None


class Server(Endpoint):
    """A server endpoint."""

    max_connections = None

    def __init__(self, protocol_factory, timeout=None):
        super(Server, self).__init__(protocol_factory, timeout=timeout)
        self._handles = []
        self._addresses = []
        self._connections = dict()
        self._all_closed = Event()
        self._all_closed.set()

    @property
    def addresses(self):
        """The addresses this server is listening on."""
        return self._addresses

    @property
    def connections(self):
        """An iterator yielding the (transport, protocol) pairs for each connection."""
        return self._connections.items()

    def _on_new_connection(self, handle, error, ssl):
        # Callback used with handle.listen().
        assert handle in self._handles
        if error:
            self._log.warning('error {} in listen() callback', error)
            return
        client = type(handle)(self._hub.loop)
        handle.accept(client)
        if self.max_connections is not None and len(self._connections) >= self.max_connections:
            self._log.warning('max connections reached, dropping new connection')
            client.close()
            return
        self.handle_connection(client, ssl)
        self._all_closed.clear()

    def handle_connection(self, client, ssl):
        """Handle a new connection with handle *client*.

        This method exists so that it can be overridden in subclass. It is not
        intended to be called directly.
        """
        if ssl:
            context = ssl if hasattr(ssl, 'set_ciphers') else ssl(client) if callable(ssl) \
                            else create_default_context(True)
            transport = SslTransport(client, context, True)
        else:
            transport = Transport(client)
        transport._log = self._log
        transport._server = self
        if __debug__:
            self._log.debug('new connection on {}', saddr(client.getsockname()))
            if hasattr(client, 'getpeername'):
                self._log.debug('remote peer is {}', saddr(client.getpeername()))
        protocol = self._protocol_factory()
        protocol._log = self._log
        protocol._timeout = self._timeout
        self._connections[transport] = protocol
        self.connection_made(transport, protocol)
        transport.start(protocol)

    def _on_close_complete(self, transport, protocol, exc=None):
        # Called by Transport._on_close_complete
        self._connections.pop(transport, None)
        if not self._connections:
            self._all_closed.set()
        self.connection_lost(transport, protocol, exc)

    def connection_made(self, transport, protocol):
        """Called when a new connection is made."""

    def connection_lost(self, transport, protocol, exc=None):
        """Called when a connection is lost."""

    @switchpoint
    def listen(self, address, ssl=False, family=0, flags=0, backlog=128):
        """Create a new transport, bind it to *address*, and start listening
        for new connections.

        See :func:`create_server` for a description of *address* and the
        supported keyword arguments.
        """
        handles = []
        if isinstance(address, six.string_types):
            handle_type = pyuv.Pipe
            addresses = [address]
        elif isinstance(address, tuple):
            handle_type = pyuv.TCP
            result = getaddrinfo(address[0], address[1], family, socket.SOCK_STREAM,
                                 socket.IPPROTO_TCP, flags)
            addresses = [res[4] for res in result]
        elif isinstance(address, pyuv.Stream):
            handles.append(address)
            addresses = []
        else:
            raise TypeError('expecting a string, tuple or pyuv.Stream')
        for addr in addresses:
            handle = handle_type(self._hub.loop)
            try:
                if handle_type is pyuv.Pipe and _use_af_unix(addr):
                    _af_unix_helper(handle, addr, 'bind')
                else:
                    handle.bind(addr)
            except pyuv.error.UVError as e:
                self._log.warning('bind error {!r}, skipping {}', e[0], saddr(addr))
                continue
            handles.append(handle)
        addresses = []
        for handle in handles:
            callback = functools.partial(self._on_new_connection, ssl=ssl)
            handle.listen(callback, backlog)
            addr = handle.getsockname()
            self._log.debug('listen on {}', saddr(addr))
            addresses.append(addr)
        self._handles += handles
        self._addresses += addresses

    @switchpoint
    def close(self):
        """Close the listening sockets and all accepted connections."""
        for handle in self._handles:
            if not handle.closed:
                handle.close()
        del self._handles[:]
        for transport, _ in self.connections:
            transport.close()
        self._all_closed.wait()

    @switchpoint
    def run(self):
        """Run the event loop and start serving requests.

        This method stops serving when a CTRL-C/SIGINT is received. It is
        useful for top-level scripts that run only one server instance. In more
        complicated application you would call :meth:`Hub.switch` directly, or
        wait on some kind of "request to shutdown" event.
        """
        try:
            get_hub().switch()
        except KeyboardInterrupt:
            pass
