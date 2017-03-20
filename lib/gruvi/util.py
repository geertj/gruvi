#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import re
import inspect
import ast
import six
import functools
import textwrap

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
        ref = '{}-{}'.format(clsname, seqno)
        _objrefs[obj] = ref
        _lastids[clsname] += 1
    return ref


re_lu = re.compile('[A-Z]+[a-z0-9]+')

def split_cap_words(s):
    """Split the CamelCase string *s* into words."""
    return re_lu.findall(s)


def delegate_method(other, method):
    """Add a method to the current class that delegates to another method.

    The *other* argument must be a property that returns the instance to
    delegate to. Due to an implementation detail, the property must be defined
    in the current class. The *method* argument specifies the method to
    delegate to.

    It is a common paragigm in Gruvi to expose protocol methods onto clients.
    This keeps most of the logic into the protocol, but prevents the user from
    having to type ``'client.protocol.*methodname*'`` all the time.

    For example::

      class MyClient(Client):

          protocol = Client.protocol

          delegate_method(protocol, MyProtocol.method)
    """
    frame = sys._getframe(1)
    classdict = frame.f_locals

    @functools.wraps(method)
    def delegate_method(self, *args, **kwargs):
        other_self = other.__get__(self)
        return method(other_self, *args, **kwargs)

    if getattr(method, '__switchpoint__', False):
        delegate_method.__switchpoint__ = True
    propname = None
    for key in classdict:
        if classdict[key] is other:
            propname = key
            break
    # If we know the property name, replace the docstring with a small
    # reference instead of copying the method docstring.
    if propname:
        delegate_method.__doc__ = 'A shorthand for ``self.{propname}.{name}()``.' \
                                .format(propname=propname, name=method.__name__)
    classdict[method.__name__] = delegate_method
