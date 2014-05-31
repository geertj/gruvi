#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import re
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
