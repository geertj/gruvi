#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import io
import sys
import threading
import socket
import errno
import pyuv


# Some compatibility stuff that is not in six.

PY3 = sys.version_info[0] == 3


# Provide a get_thread_ident() that is the same on Python 2.x and 3.x

try:
    get_thread_ident = threading._get_ident
except AttributeError:
    get_thread_ident = threading.get_ident


# Support for re-raising stored exceptions. In our callback based code it is
# very common that we store an exception in a callback as an instance
# attribute, and then raise that from the consumer API. This is problematic on
# Python3 because the traceback in Py3K is attached to the exception itself (as
# the __traceback__ attribute). The impact is that i) the traceback will also
# be stored and never freed, and ii) if the exception is re-raised multiple times
# a new traceback will be appended for every raise.
#
# The solution that we're using is is to have a saved_exc() call that returns a
# new copy of the exception on Python3.

if PY3:
    def saved_exc(exc):
        if isinstance(exc, type):
            return exc
        return type(exc)(*exc.args)
else:
    def saved_exc(exc):
        return exc


# Support write_through for TextIOWrapper on Python 2.x. The write_through
# argument first appeared in Python 3.3.

if PY3:

    TextIOWrapper = io.TextIOWrapper

else:

    class TextIOWrapper(io.TextIOWrapper):

        def __init__(self, *args, **kwargs):
            self._write_through = kwargs.pop('write_through', False)
            super(TextIOWrapper, self).__init__(*args, **kwargs)

        def write(self, buf):
            super(TextIOWrapper, self).write(buf)
            if self._write_through:
                self.flush()

        def writelines(self, seq):
            super(TextIOWrapper, self).writelines(seq)
            if self._write_through:
                self.flush()


# Needed until pyuv accepts PR #249 and #250

def pyuv_pipe_helper(handle, handle_args, op, addr):
    if not isinstance(handle, pyuv.Pipe):
        return False
    # Store the 'ipc' constructor argument.
    if handle_args and not hasattr(handle, 'ipc'):
        handle.ipc = handle_args[0]
    if not sys.platform.startswith('linux') or '\x00' not in addr:
        return False
    # Connect or bind the socket.
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        if op == 'connect':
            sock.connect(addr)
        elif op == 'bind':
            sock.bind(addr)
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
    # Work around a bug in pyuv where abstract sockets names are reported as
    # bytes by dynamically patching getsockname(). The above PRs should fix this.
    if PY3:
        self = handle
        encoding = sys.getfilesystemencoding()
        def getsockname():
            value = type(handle).getsockname(self)
            if isinstance(value, bytes):
                value = value.decode(encoding)
            return value
        handle.getsockname = getsockname
    return True
