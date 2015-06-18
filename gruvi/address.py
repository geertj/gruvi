#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import six
import pyuv

from .hub import get_hub, switch_back, switchpoint

__all__ = ['saddr', 'paddr', 'getaddrinfo', 'getnameinfo']


def saddr(address):
    """Return a string representation for an address.

    The *address* paramater can be a pipe name, an IP address tuple, or a
    socket address.

    The return value is always a ``str`` instance.
    """
    if isinstance(address, six.binary_type) and six.PY3:
        return address.decode('utf8')
    elif isinstance(address, six.string_types):
        return address
    elif isinstance(address, tuple) and ':' in address[0]:
        return '[{}]:{}'.format(address[0], address[1])
    elif isinstance(address, tuple):
        return '{}:{}'.format(*address)
    else:
        raise TypeError('illegal address type: {!s}'.format(type(address)))


def paddr(address):
    """Parse a string representation of an address.

    This function is the inverse of :func:`saddr`.
    """
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
def getaddrinfo(node, service=0, family=0, socktype=0, protocol=0, flags=0, timeout=30):
    """Resolve an Internet *node* name and *service* into a socket address.

    The *family*, *socktype* and *protocol* are optional arguments that specify
    the address family, socket type and protocol, respectively. The *flags*
    argument allows you to pass flags to further modify the resolution process.
    See the :func:`socket.getaddrinfo` function for a detailed description of
    these arguments.

    The return value is a list of ``(family, socktype, proto, canonname,
    sockaddr)`` tuples. The fifth element (``sockaddr``) is the socket address.
    It will be a 2-tuple ``(addr, port)`` for an IPv4 address, and a 4-tuple
    ``(addr, port, flowinfo, scopeid)`` for an IPv6 address.

    The address resolution is performed in the libuv thread pool.
    """
    hub = get_hub()
    with switch_back(timeout) as switcher:
        request = pyuv.dns.getaddrinfo(hub.loop, node, service, family,
                                       socktype, protocol, flags, callback=switcher)
        switcher.add_cleanup(request.cancel)
        result = hub.switch()
    result, error = result[0]
    if error:
        message = pyuv.errno.strerror(error)
        raise pyuv.error.UVError(error, message)
    return result


@switchpoint
def getnameinfo(sockaddr, flags=0, timeout=30):
    """Resolve a socket address *sockaddr* back to a ``(node, service)`` tuple.

    The *flags* argument can be used to modify the resolution process. See the
    :func:`socket.getnameinfo` function for more information.

    The address resolution is performed in the libuv thread pool.
    """
    hub = get_hub()
    with switch_back(timeout) as switcher:
        request = pyuv.dns.getnameinfo(hub.loop, sockaddr, flags, callback=switcher)
        switcher.add_cleanup(request.cancel)
        result = hub.switch()
    result, error = result[0]
    if error:
        message = pyuv.errno.strerror(error)
        raise pyuv.error.UVError(error, message)
    return result
