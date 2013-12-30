#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import socket
import pyuv

from .hub import get_hub, switchpoint

# The Handle base class is not exposed by pyuv
pyuv.Handle = pyuv.UDP.__bases__[0]

__all__ = ['TCP', 'UDP', 'Pipe', 'TTY']


def pyuv_exc(transport, error):
    """Return a suitable exception for *transport* with errno set to *error*."""
    if isinstance(transport, pyuv.TCP):
        exc = pyuv.error.TCPError
    elif isinstance(transport, pyuv.UDP):
        exc = pyuv.error.UDPError
    elif isinstance(transport, pyuv.Pipe):
        exc = pyuv.error.PipeError
    else:
        exc = pyuv.error.Error
    message = pyuv.errno.strerror(error)
    return exc(error, message)


class TCP(pyuv.TCP):
    """A TCP transport.
    
    For the API reference, see :class:`pyuv.TCP`
    """

    def __init__(self):
        super(TCP, self).__init__(get_hub().loop)


class UDP(pyuv.UDP):
    """A UDP transport.

    For the API reference, see :class:`pyuv.UDP`
    """

    def __init__(self):
        super(UDP, self).__init__(get_hub().loop)


class Pipe(pyuv.Pipe):
    """A Pipe transport.

    For the API reference, see :class:`pyuv.Pipe`

    One extension to the pyuv version is that this class allows you to connect
    to abstract sockets on Linux, which are used for example by for D-BUS. To
    connect to an abstract socket use the Linux convention of starting the
    address string with a null byte (``'\\x00'``).
    """

    def __init__(self, ipc=False):
        super(Pipe, self).__init__(get_hub().loop, ipc)

    def bind(self, name):
        super(Pipe, self).bind(name)
        self.address = name

    def connect(self, address, callback=None):
        # Support for abstract sockets on Linux, which are needed for D-BUS.
        # Abstract sockets don't work with libuv/pyuv Pipe because libuv
        # expects the socket name to be a zero terminated string, while Linux
        # identifies abstract sockets as those having a name starting with a
        # null byte.
        # We work around this by opening the socket ourselves and then use
        # Pipe.open to open the socket's descriptor.
        if not address.startswith('\x00'):
            super(Pipe, self).connect(address, callback)
            self.address = address
            return
        if sys.platform != 'linux2':
            raise RuntimeError('abstract sockets are Linux only')
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.setblocking(False)
        try:
            self._sock.connect(address)
        except socket.error as e:
            error = e.args[0]
        else:
            error = 0
            self.open(self._sock.fileno())
        self.address = address
        # On Linux, connect() on a Unix domain socket never blocks. So we can
        # notify success (or failure) immmediately.
        if callback:
            callback(self, error)


class TTY(pyuv.TTY):
    """A TTY transport.

    For the API reference, see :class:`pyuv.TTY`
    """

    def __init__(self, fd, readable=1):
        if hasattr(fd, 'fileno'):
            readable = 'r' in fd.mode
            fd = fd.fileno()
        super(TTY, self).__init__(get_hub().loop, fd, readable)
