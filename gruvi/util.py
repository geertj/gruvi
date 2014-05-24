#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import re
import threading
import six

from weakref import WeakKeyDictionary

__all__ = []


def docfrom(base):
    """Decorator to set a function's docstring from another function."""
    def setdoc(func):
        func.__doc__ = (getattr(base, '__doc__') or '') + (func.__doc__ or '')
        return func
    return setdoc


_objrefs = WeakKeyDictionary()  # obj -> objref
_lastids = {}  # classname -> lastid

def objref(obj):
    """Return a string that uniquely and compactly identifies an object."""
    ref = _objrefs.get(obj)
    if ref is None:
        clsname = obj.__class__.__name__.split('.')[-1]
        seqno = _lastids.setdefault(clsname, 1)
        ref = '{0}-{1}'.format(clsname, seqno)
        _objrefs[obj] = ref
        _lastids[clsname] += 1
    return ref


re_lu = re.compile('[A-Z]+[a-z0-9]+')

def split_cap_words(s):
    """Split the CamelCase string *s* into words."""
    return re_lu.findall(s)


# Support Python 2.7+ implictly indexed positional argument specifiers also on
# Python 2.6. Also remove the non-supported ',' format specifier

# {{ and }} are escape characters. Use negative lookbehind/ahead to ensure
# an odd number of braces on either side.
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
if six.PY3:
    get_thread_ident = threading.get_ident
else:
    get_thread_ident = threading._get_ident
