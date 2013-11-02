#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import weakref
import fibers

__all__ = ['local']


class local(object):
    """Fiber local storage.
    
    The API for local storage is the same as that of :class:`threading.local`.
    To create a fiber local value, instantiate this class and store attributes
    on it::

        mydata = local()
        mydata.x = 10

    The values of the attributes will be different (or unset) for different
    fibers.
    """

    def __init__(self):
        self.__dict__['_keys'] = weakref.WeakKeyDictionary()

    def __getattr__(self, key):
        current = fibers.current()
        try:
            return self._keys[current][key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        current = fibers.current()
        self._keys.setdefault(current, {})[key] = value

    def __delattr__(self, key):
        current = fibers.current()
        try:
            del self._keys[current][key]
        except KeyError:
            raise AttributeError(key)
