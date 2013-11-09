#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
import socket
from weakref import WeakKeyDictionary

from . import compat
from .hub import switchpoint, get_hub, switch_back
from .pyuv import pyuv_exc, TCP, Pipe
from .ssl import SSL
from .error import Timeout

__all__ = ['sleep', 'saddr', 'getaddrinfo', 'create_connection', 'getsockname']


_objrefs = WeakKeyDictionary()  # obj -> objref
_lastids = {}  # classname -> lastid

def objref(obj):
    """Return a string that uniquely and compactly identifies an object."""
    ref = _objrefs.get(obj)
    if ref is None:
        clsname = obj.__class__.__name__.split('.')[-1]
        seqno = _lastids.setdefault(clsname, 1)
        ref = '{0}#{1}'.format(clsname, seqno)
        _objrefs[obj] = ref
        _lastids[clsname] += 1
    return ref


def docfrom(base):
    """Decorator to set a function's docstring from another function."""
    def setdoc(func):
        func.__doc__ = (getattr(base, '__doc__') or '') + (func.__doc__ or '')
        return func
    return setdoc


@switchpoint
def sleep(secs):
    """Sleep for *secs* seconds."""
    hub = get_hub()
    try:
        with switch_back(secs):
            hub.switch()
    except Timeout:
        pass


def saddr(address):
    """Return a family specific string representation for a socket address."""
    if isinstance(address, compat.binary_type) and compat.PY3:
        return address.decode('utf8')
    elif isinstance(address, compat.string_types):
        return address
    elif isinstance(address, tuple) and ':' in address[0]:
        return '[{0}]:{1}'.format(address[0], address[1])
    elif isinstance(address, tuple):
        return '{0}:{1}'.format(*address)
    elif isinstance(address, pyuv.Handle):
        return '{0!r}'.format(address)
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
        result = hub.switch()
    args, kwargs = result
    if args[1]:
        raise pyuv_exc(None, args[1])
    return args[0]


@switchpoint
def create_connection(address, ssl=False, local_address=None,
                      timeout=None, **transport_args):
    """Connect to *address*, wait for the connection to be established, and
    return the connected transport.

    The address may be either be a string, a (host, port) tuple, or an already
    connected stream transport. If the address is a string, this method
    connects to a named pipe using a :class:`.Pipe` transport.  If the address
    is a tuple, this method connects to a TCP/IP service, using a :class:`.TCP`
    or a :class:`.SSL` transport, depending on the value of *ssl*. The host and
    port elements of the tuple may be DNS and service names respectively, and
    will be resolved using :func:`~gruvi.util.getaddrinfo`.

    The *local_address* keyword argument is relevant only for TCP and SSL
    transports. If provided, it specifies the local address to bind to.

    Extra keyword arguments may be provided in *transport_args*. These will
    be passed to the constructor of the transport that is being used. This
    is useful when using SSL.

    Finally, *address* may also be an already connected stream transport.
    In this case, all other arguments are ignored.
    """
    hub = get_hub()
    from . import logging
    log = logging.get_logger('create_connection()')
    if isinstance(address, (compat.binary_type, compat.text_type)):
        transport_type = Pipe
        addresses = [address]
    elif isinstance(address, tuple):
        transport_type = SSL if ssl else TCP
        result = getaddrinfo(address[0], address[1], socket.AF_UNSPEC,
                             socket.SOCK_STREAM, socket.IPPROTO_TCP)
        addresses = [res[4] for res in result]
    elif isinstance(address, pyuv.Handle):
        transport = address
        addresses = []; error = None; local_address = None
    else:
        raise TypeError('expecting a string, tuple, or transport')
    for addr in addresses:
        log.debug('trying address {0}'.format(saddr(addr)))
        transport = transport_type(**transport_args)
        with switch_back(timeout) as switcher:
            try:
                transport.connect(addr, switcher)
                hub.switch()
            except pyuv.error.UVError as e:
                error = e[0]
            except Timeout:
                error = pyuv.errno.UV_ETIMEDOUT
            else:
                error = None
        if not error:
            break
        log.warning('connect() failed with error {0}'.format(error))
    if error:
        log.error('all addresses failed')
        raise pyuv_exc(transport, error)
    if local_address:
        transport.bind(*local_address)
    return transport


def getsockname(transport):
    """Return the socket name of a transport."""
    if hasattr(transport, 'getsockname'):
        return transport.getsockname()
    elif hasattr(transport, 'address'):
        return transport.address
    else:
        raise TypeError('cannot get address for type "{0}"'
                            .format(type(transport).__name__))
