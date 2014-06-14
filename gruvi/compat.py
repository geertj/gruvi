#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import re
import threading
import functools


# Some compatibility stuff that is not in six.

PY26 = sys.version_info[:2] == (2, 6)
PY3 = sys.version_info[0] == 3

if PY26:

    memoryview = buffer   # read-only but close enough for us
    bytes_types = (bytes, bytearray, buffer)  # flake8: noqa

else:

    memoryview = memoryview
    bytes_types = (bytes, bytearray, memoryview)

    fixup_format_string = lambda fmt: fmt


# Support Python 2.7+ implictly indexed positional argument specifiers also on
# Python 2.6. Also remove the non-supported ',' format specifier

# {{ and }} are escape characters. Use negative lookbehind/ahead to ensure an
# odd number of braces on either side.
re_pos_arg = re.compile(r'(?<!\{)((?:\{\{)*\{)([:!][^}]+)?(\}(?:\}\})*)(?!\})')

def fixup_format_string(fmt):
    """Transform a format string with implicitly numbered positional arguments
    so that it will work on Python 2.6."""
    count = [0]
    def replace(mobj):
        field = str(count[0]); count[0] += 1
        spec = (mobj.group(2) or '').replace(',', '')
        return mobj.group(1) + field + spec + mobj.group(3)
    return re_pos_arg.sub(replace, fmt)


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

def _textiowrapper_write(self, buf):
    ret = self._orig_write(buf)
    self.flush()
    return ret

def _textiowrapper_writelines(self, seq):
    ret = self._orig_writelines(seq)
    self.flush()
    return ret

def make_textiowrapper_writethrough(wrapper):
    """Enable write_through for a TextIOWrapper."""
    wrapper._orig_write = wrapper.write
    wrapper.write = functools.partial(_textiowrapper_write, wrapper)
    wrapper._orig_writelines = wrapper.writelines
    wrapper.writelines = functools.partial(_textiowrapper_writelines, wrapper)
