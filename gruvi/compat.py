#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import threading
import re


# Some compatibility stuff that is not in six.

PY26 = sys.version_info[:2] == (2, 6)

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
