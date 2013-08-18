#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

import sys
import inspect


def getqualname(obj):
    if hasattr(obj, '__qualname__'):
        name = obj.__qualname__
    elif inspect.ismethod(obj):
        name = '{0}.{1}'.format(obj.im_self.__class__.__name__, obj.__name__)
    elif hasattr(obj, '__name__'):
        name = obj.__name__
    else:
        name = repr(obj)
    return name
