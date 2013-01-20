#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import pyuv
import gruvi
import errno
import socket
import _socket
import six


nonblocking_errors = (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR)
connect_errors = (errno.EINPROGRESS, errno.EALREADY)
already_connected = (errno.EISCONN,)


def sock_retry(sock, method, args=(), retry_read=None, retry_write=None,
               ignore=None):
    start_time = sock.hub.loop.now()
    timeout = sock.gettimeout()
    while True:
        try:
            return method(*args)
        except socket.error as e:
            if retry_read and e.errno in retry_read:
                events = pyuv.UV_READABLE
            elif retry_write and e.errno in retry_write:
                events = pyuv.UV_WRITABLE
            elif ignore and e.errno in ignore:
                return
            else:
                raise
        if timeout is not None:
            elapsed = sock.hub.loop.now() - start_time
            if elapsed > sock.timeout:
                raise socket.timeout()
            secs = timeout - elapsed
            sock.timer.start(sock.hub.switch_back(), secs, 0)
        sock.poll.start(events, sock.hub.switch_back())
        sock.hub.switch()
        if timeout is not None:
            sock.timer.stop()
        sock.poll.stop()


class Socket(object):
    """A network socket.

    This object implements synchronous, evented IO to a network socket
    and is compatible with Python's socket.SocketType.
    """

    def __init__(self, hub, family=socket.AF_INET, type=socket.SOCK_STREAM,
                 proto=0, _sock=None):
        if _sock is None:
            if six.PY3:
                _sock = socket.socket(family, type, proto)
            else:
                _sock = _socket.socket(family, type, proto)
        self._sock = _sock
        self.hub = hub
        self.poll = pyuv.Poll(hub.loop, self.fileno())
        self.timer = pyuv.Timer(hub.loop)
        self.setblocking(True)

    def fileno(self):
        return self._sock.fileno()

    def dup(self):
        return Socket(_sock=self._sock)

    def getblocking(self):
        return self.timeout is None

    def setblocking(self, flag):
        self.timeout = None if flag else 0
        self._sock.settimeout(0)

    def gettimeout(self):
        return self.timeout

    def settimeout(self, timeout):
        self.timeout = timeout
        self._sock.settimeout(0)

    def getsockname(self):
        return self._sock.getsockname()

    def getpeername(self):
        return self._sock.getpeername()

    def bind(self, address):
        self._sock.bind(address)

    def listen(self, backlog):
        self._sock.listen(backlog)

    def accept(self):
        conn, addr = sock_retry(self, self._sock.accept,
                                retry_read=nonblocking_errors)
        conn = Socket(self.hub, _sock=conn)
        return conn, addr

    def connect(self, address):
        sock_retry(self, self._sock.connect, (address,),
                   retry_write=connect_errors, ignore=already_connected)

    def connect_ex(self, address):
        try:
            self.connect(address)
            return 0
        except socket.error as e:
            return e.errno

    def recv(self, nbytes=1024, flags=0):
        return sock_retry(self, self._sock.recv, (nbytes, flags),
                          retry_read=nonblocking_errors)

    def recv_into(self, buffer, nbytes=None, flags=0):
        return sock_retry(self, self._sock.recv_into, (bufffer, nbytes, flags),
                          retry_read=nonblocking_errors)

    def recvfrom(self, nbytes=1024, flags=0):
        return sock_retry(self, self._sock.recvfrom, (nbytes, flags),
                          retry_read=nonblocking_errors)

    def recvfrom_info(self, buffer, nbytes=None, flags=0):
        return sock_retry(self, self._sock.recvfrom_into, (buffer, nbytes, flags),
                          retry_read=nonblocking_errors)

    def send(self, data, flags=0):
        return sock_retry(self, self._sock.send, (data, flags),
                          retry_write=nonblocking_errors)

    def sendto(self, data, flags_or_addr, addr=None):
        return sock_retry(self, self._sock.sendto, (data, flags_or_addr, addr),
                          retry_write=nonblocking_errors)

    def sendall(self, data, flags=0):
        offset = 0
        buf = buffer(data)  # zero-copy slices
        while offset != len(buf):
            nbytes = self.send(data[offset:])
            offset += nbytes

    def close(self):
        self._sock.close()

    def shutdown(self, how):
        self._sock.shutdown(how)
    
    def getsockopt(self, level, option, buffersize=0):
        return self._sock.getsockopt(level, option, buffersize)

    def setsockopt(self, level, option, value):
        self._sock.setsockopt(level, option, value)

    family = property(lambda self: self._sock.family)
    type = property(lambda self: self._sock.type)
    proto = property(lambda self: self._sock.proto)
