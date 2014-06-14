#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import socket
import functools
import textwrap
import inspect
import pyuv
import six
import errno

from . import logging
from .hub import get_hub, switchpoint, switch_back
from .sync import Event
from .errors import Timeout
from .transports import TransportError, Transport
from .ssl import SslTransport, create_ssl_context

__all__ = ['saddr', 'paddr', 'getaddrinfo', 'create_connection',
           'create_server', 'Server']


def saddr(address):
    """Return a family specific string representation for a socket address."""
    if isinstance(address, six.binary_type) and six.PY3:
        return address.decode('utf8')
    elif isinstance(address, six.string_types):
        return address
    elif isinstance(address, tuple) and ':' in address[0]:
        return '[{0}]:{1}'.format(address[0], address[1])
    elif isinstance(address, tuple):
        return '{0}:{1}'.format(*address)
    else:
        raise TypeError('illegal address type: {!s}'.format(type(address)))


def paddr(address):
    """The inverse of saddr."""
    if address.startswith('['):
        p1 = address.find(']:')
        if p1 == -1:
            raise ValueError
        return (address[1:p1], int(address[p1+2:]))
    elif ':' in address:
        p1 = address.find(':')
        return (address[:p1], int(address[p1+1:]))
    else:
        return address


@switchpoint
def getaddrinfo(host, port=0, family=0, socktype=0, protocol=0, flags=0, timeout=30):
    """A cooperative version of :py:func:`socket.getaddrinfo`.

    The address resolution is performed in the libuv thread pool.
    """
    hub = get_hub()
    with switch_back(timeout) as switcher:
        request = pyuv.util.getaddrinfo(hub.loop, switcher, host, port, family,
                                        socktype, protocol, flags)
        switcher.add_cleanup(request.cancel)
        result = hub.switch()
    result, error = result[0]
    if error:
        message = pyuv.errno.strerror(error)
        raise pyuv.error.UVError(error, message)
    return result


def create_handle(cls, *args):
    """Create a pyuv handle, connecting it to the default loop."""
    hub = get_hub()
    return cls(hub.loop, *args)


def _use_af_unix():
    """Return whether to open a :class:`pyuv.Pipe` via an AF_UNIX socket."""
    # Only use on platforms that don't return EAGAIN for AF_UNIX sockets
    return sys.platform in ('linux', 'linux2', 'linux3')

def _af_unix_helper(handle, address, op):
    """Connect or bind a :class:`pyuv.Pipe` to an AF_UNIX socket.

    We use this on Linux to work around certain limitations in the libuv API,
    currently the lack of abstract sockets and SO_PEERCRED.
    """
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
        errname = 'UV_{0}'.format(errno.errocode.get(e.errno, 'UNKNOWN'))
        errnum = getattr(pyuv.errno, errname, pyuv.errno.UV_UNKNOWN)
        raise pyuv.error.PipeError(errnum, os.strerror(e.errno))
    finally:
        sock.close()
    handle.open(fd)


@switchpoint
def create_connection(protocol_factory, address, ssl=False, ssl_args={},
                      family=0, flags=0, local_address=None, timeout=None):
    """Create a new connection.

    This method creates a stream transport, connects it to *address*, and then
    waits for the connection to be established. When the connection is
    established, a new protocol instance is created by calling
    *protocol_factory*. The protocol is then connected to the transport by
    calling its ``conection_made`` method. Finally the results are returned as
    a ``(transport, protocol)`` tuple.

    The address may be either be a string, a (host, port) tuple, or an already
    connected :class:`pyuv.Stream` handle. If the address is a string, this
    method connects to a named pipe using a :class:`pyuv.Pipe` handle.

    If the address is a tuple, this method connects to a TCP/IP service using a
    :class:`pyuv.TCP` handle. The host and port elements of the tuple are the
    DNS and service names respectively, and will be resolved using
    :func:`getaddrinfo`. The *family* and *flags* parameters are also passed to
    :func:`getaddrinfo` and can be used to modify the address resolution.

    The address my also be a :class:`pyuv.Stream` instance. In this case the
    handle must already be connected.

    The *ssl* parameter indicates whether SSL should be used on top of the
    stream transport. If an SSL connection is desired, then *ssl* can be set to
    ``True`` or to an :class:`ssl.SSLContext` instance. In the former case a
    default SSL context is created. In the case of Python 2.x the :mod:`ssl`
    module does not define an SSL context object and you may use the
    :class:`gruvi.sslcompat.SSLContext` class instead. The *ssl_args* argument
    may be used to pass keyword arguments to
    :meth:`ssl.SSLContext.wrap_socket`.

    If an SSL connection was selected, the resulting transport will be a
    :class:`gruvi.SslTransport` instance, otherwise it will be a
    :class:`gruvi.Transport` instance.

    The *local_address* keyword argument is relevant only for AF_INET
    transports. If provided, it specifies the local address to bind to.
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
    elif isinstance(address, pyuv.Stream):
        handle = address
        addresses = []; error = None
    else:
        raise TypeError('expecting a string, tuple, or pyuv.Stream')
    for addr in addresses:
        log.debug('trying address {}', saddr(addr))
        handle = handle_type(hub.loop)
        try:
            if handle_type is pyuv.Pipe and _use_af_unix():
                _af_unix_helper(handle, addr, 'connect')
            else:
                with switch_back(timeout) as switcher:
                    handle.connect(addr, switcher)
                    hub.switch()
        except pyuv.error.UVError as e:
            error = e[0]
        except Timeout:
            error = pyuv.errno.UV_ETIMEDOUT
        else:
            error = None
        if not error:
            break
        log.warning('connect() failed with error {}', error)
    if error:
        log.error('all addresses failed')
        raise TransportError.from_errno(error)
    if local_address:
        handle.bind(*local_address)
    protocol = protocol_factory()
    if ssl:
        context = ssl if hasattr(ssl, '_wrap_socket') else create_ssl_context()
        transport = SslTransport(handle, context, False, **ssl_args)
    else:
        transport = Transport(handle)
    event = transport.start(protocol)
    if event is not None:
        event.wait()
    return (transport, protocol)


class Endpoint(object):
    """A communications endpoint."""

    def __init__(self, protocol_factory, timeout=None):
        self._protocol_factory = protocol_factory
        self._timeout = timeout
        self._hub = get_hub()
        self._log = logging.get_logger(self)

    @property
    def timeout(self):
        return self._timeout


class Client(Endpoint):
    """A client endpoint."""

    def __init__(self, protocol_factory, timeout=None):
        super(Client, self).__init__(protocol_factory, timeout=timeout)
        self._connection = None

    @property
    def connection(self):
        """Return the ``(transport, protocol)`` pair, or None if not connected."""
        return self._connection

    @switchpoint
    def connect(self, address, **kwargs):
        """Connect to *address* and wait for the connection to be established.

        See :func:`create_connection` for a description of *address* and the
        supported keyword arguments.
        """
        if self._connection:
            raise RuntimeError('already connected')
        kwargs.setdefault('timeout', self.timeout)
        self._connection = create_connection(self._protocol_factory, address, **kwargs)
        self._connection[0]._log = self._log
        self._connection[1]._log = self._log

    @switchpoint
    def close(self):
        """Close the connection."""
        if not self._connection:
            return
        protocol = self._connection[1]
        protocol.close()
        self._connection = None


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
        """A list of all listen addresses."""
        return self._addresses

    @property
    def connections(self):
        """An iterator yielding the (transport, protocol) pairs for each connection."""
        return self._connections.items()

    def _on_new_connection(self, ssl, ssl_args, handle, error):
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
        if ssl:
            context = ssl if hasattr(ssl, '_wrap_socket') else create_ssl_context()
            transport = SslTransport(client, context, True, **ssl_args)
        else:
            transport = Transport(client)
        transport._log = self._log
        self._all_closed.clear()
        self._log.debug('new connection on {}', saddr(client.getsockname()))
        if hasattr(client, 'getpeername'):
            self._log.debug('remote peer is {}', saddr(client.getpeername()))
        protocol = self._protocol_factory()
        protocol._log = self._log
        self._connections[transport] = protocol
        # Chain _on_connection_lost() into protocol.connection_lost()
        protocol.connection_lost = functools.partial(self._on_connection_lost, transport,
                                                     protocol, protocol.connection_lost)
        self.connection_made(transport, protocol)
        transport.start(protocol)

    def _on_connection_lost(self, transport, protocol, connection_lost, *args):
        self.connection_lost(transport, protocol, *args)
        connection_lost(*args)
        self._connections.pop(transport, None)
        if not self._connections:
            self._all_closed.set()

    def connection_made(self, transport, protocol):
        """Callback that is called when a new connection is made."""

    def connection_lost(self, transport, protocol, *args):
        """Callback that is called when a connection is lost."""

    @switchpoint
    def listen(self, address, ssl=False, ssl_args={}, family=0, flags=0, backlog=128):
        """Create a new transport, bind it to *address*, and start listening
        for new connections.

        The address may be either be a string, a (host, port) tuple, or a
        :class:`pyuv.Stream` handle.  If the address is a string, this method
        creates a new :class:`pyuv.Pipe` instance, binds it to *address* and
        will start listening for new connections on it.

        If the address is a tuple, this method creates a new :class:`pyuv.TCP`
        handle. The host and port elements of the tuple are the DNS or IP
        address, and service name or port number respectively. They will be
        resolved resolved using :func:`getaddrinfo()`. The *family* and *flags*
        parameters are also passed to :func:`getaddrinfo` and can be used to
        modify the address resolution. The server will listen on all addresses
        that are resolved.

        The address may also a :class:`pyuv.Stream` handle. In this case it
        must already be bound to an address.

        The *ssl* parameter indicates whether SSL should be used for accepted
        connections. See :func:`create_connection` for a description of the
        *ssl* and *ssl_args* parameters.

        The *backlog* parameter specifies the listen backlog i.e the maximum
        number of not yet accepted connections to queue.
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
                if handle_type is pyuv.Pipe and _use_af_unix():
                    _af_unix_helper(handle, addr, 'bind')
                else:
                    handle.bind(addr)
            except pyuv.error.UVError as e:
                self._log.warning('bind error {!r}, skipping {}', e[0], saddr(addr))
                continue
            handles.append(handle)
        addresses = []
        for handle in handles:
            callback = functools.partial(self._on_new_connection, ssl, ssl_args)
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
            handle.close()
        del self._handles[:]
        for transport, _ in self.connections:
            transport.close()
        self._all_closed.wait()


@switchpoint
def create_server(protocol_factory, address=None, ssl=False, ssl_args={},
                  family=0, flags=0, backlog=128):
    """Create a new network server.

    This method creates a new :class:`Server` instance and calls
    :meth:`Server.listen` on it to listen for new connections. The server
    instance is returned.

    For a description of the arguments of this function, see
    :meth:`Server.listen`.
    """
    server = Server(protocol_factory)
    server.listen(address, ssl=ssl, ssl_args=ssl_args, family=family,
                  flags=flags, backlog=backlog)
    return server


_protocol_method_template = textwrap.dedent("""\
    def {name}{signature}:
        '''{docstring}'''
        if not self.connection:
            raise RuntimeError('not connected')
        return self.connection[1].{name}{arglist}
    """)

def add_protocol_method(method, moddict, classdict):
    """Import a method from a :class:`Protocol` into a :class:`Client`."""
    name = method.__name__
    doc = method.__doc__ or ''
    argspec = inspect.getargspec(method)
    signature = inspect.formatargspec(*argspec)
    arglist = inspect.formatargspec(argspec[0][1:], *argspec[1:], formatvalue=lambda x: '')
    methoddef = _protocol_method_template.format(name=name, signature=signature,
                                                 docstring=doc, arglist=arglist)
    code = compile(methoddef, moddict['__file__'], 'exec')
    globs = {}
    six.exec_(code, globs)
    wrapped = globs[name]
    if getattr(method, 'switchpoint', False):
        wrapped = switchpoint(wrapped)
    classdict[name] = wrapped
