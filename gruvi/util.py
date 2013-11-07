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

from . import compat
from .hub import switchpoint, get_hub
from .pyuv import pyuv_exc, TCP, Pipe
from .ssl import SSL

__all__ = ['sleep', 'saddr', 'getaddrinfo', 'create_connection']


_lastids = {}  # name -> lastid

def objref(obj):
    """Return a string that uniquely and compactly identifies an object."""
    if not hasattr(obj, '_objref'):
        clsname = obj.__class__.__name__.split('.')[-1]
        seqno = _lastids.setdefault(clsname, 1)
        ref = '{0}#{1}'.format(clsname, seqno)
        obj._objref = ref
        _lastids[clsname] += 1
    return obj._objref


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
    hub.switch(secs)


def saddr(address):
    """Return a family specific string representation for a socket address."""
    if isinstance(address, (compat.binary_type, compat.text_type)):
        return address
    elif isinstance(address, tuple) and len(address) == 2:
        return '{0}:{1}'.format(*address)
    elif isinstance(address, tuple) and len(address) == 4:
        return '[{0}]:{1}/{2}/{3}'.format(*address)
    else:
        raise TypeError('illegal address type')


@switchpoint
def getaddrinfo(host, port=0, family=0, socktype=0, protocol=0, flags=0,
                timeout=30):
    """A cooperative version of :py:func:`socket.getaddrinfo`.

    The address resolution is performed in the libuv thread pool. 
    """
    hub = get_hub()
    request = pyuv.util.getaddrinfo(hub.loop, hub.switch_back(), host, port,
                                    family, socktype, protocol, flags)
    result = hub.switch(timeout)
    request.cancel()
    if not result:
        raise pyuv_exc(None, pyuv.errno.UV_TIMEDOUT)
    elif result[1]:
        raise pyuv_exc(None, result[1])
    return result[0]


@switchpoint
def create_connection(address, ssl=False, local_address=None,
                      timeout=None, **transport_args):
    """Connect to *address*, and wait for the connection to be established.

    The address may be either be a string, a (host, port) tuple, or an
    already connected stream transport. If the address is a string, this
    method connects to a named pipe using a ``pyuv.Pipe`` transport.  If
    the address is a tuple, this method connects to a TCP/IP service, using
    a ``pyuv.TCP`` or a ``ssl.SSL`` transport, depending on the value of
    *ssl*. The host and port elements of the tuple may be DNS and service
    names respectively, and will be resolved using
    :func:`gruvi.util.getaddrinfo`.

    The *local_address* keyword argument is relevant only for TCP and SSL
    transports. If provided, it specifies the local address to bind to.

    Extra keyword arguments may be provided in *transport_args*. These will
    be passed to the constructor of the transport that is being used. This
    is useful when using SSL.

    Finally, *address* may also be an already connected stream transport.
    In this case, all other arguments are ignored.
    """
    from . import logging
    logger = logging.get_logger('create_connection()')
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
        logger.debug('trying address {0}'.format(saddr(addr)))
        transport = transport_type(**transport_args)
        try:
            transport.connect(addr, get_hub().switch_back())
        except pyuv.error.UVError as e:
            error = e[0]
        else:
            result = get_hub().switch(timeout)
            error = pyuv.errno.UV_ETIMEDOUT if not result else result[1]
        if not error:
            break
        logger.warning('connect() failed with error {0}'.format(error))
    if error:
        logger.error('all addresses failed')
        raise pyuv_exc(transport, error)
    if local_address:
        transport.bind(*local_address)
    return transport
