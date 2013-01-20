#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import weakref
import greenlet


class local(object):
    """A greenlet local object.
    
    Attributes on this object are local to the current greenlet.
    """

    def __init__(self):
        super(local, self).__init__()
        self.__dict__['_local__dicts'] = {}
        self.__dict__['_local__refs'] = {}

    def __getattr__(self, key):
        grid = id(greenlet.getcurrent())
        print('__getattr__(): grid: %s' % grid)
        try:
            return self.__dicts[grid][key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        grid = id(greenlet.getcurrent())
        if grid not in self.__dicts:
            self.__dicts[grid] = {}
            def cleanup(ref):
                del self.__dicts[grid]
                del self.__refs[grid]
            ref = weakref.ref(greenlet.getcurrent(), cleanup)
            self.__refs[grid] = ref
        self.__dicts[grid][key] = value

    def __delattr__(self, key):
        grid = id(greenlet.getcurrent())
        try:
            del self.__dicts[grid][key]
        except KeyError:
            raise AttributeError(key)
