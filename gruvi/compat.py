#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

import sys
import inspect


PY3 = sys.version_info >= (3, 0, 0)

if PY3 and sys.version_info < (3, 3):
    raise RuntimeError('Python 3 support requires Python >= 3.3')
elif not PY3 and sys.version_info < (2, 6):
    raise RuntimeError('Python 2.x support requires Python >= 2.6')


# Some code copied from the "six" package below. MIT Licensed.

if PY3:
    binary_type = bytes
    text_type = str
    string_types = (str,)
    integer_types = (int,)

    next = next

    import builtins
    exec_ = getattr(builtins, "exec")

    def reraise(tp, value, tb=None):
        if value.__traceback__ is not tb:
            raise value.with_traceback(tb)
        raise value

else:
    binary_type = str
    text_type = unicode
    string_types = (basestring,)
    integer_types = (int, long)

    def next(it):
        return it.next()

    def exec_(_code_, _globs_=None, _locs_=None):
        """Execute code in a namespace."""
        if _globs_ is None:
            frame = sys._getframe(1)
            _globs_ = frame.f_globals
            if _locs_ is None:
                _locs_ = frame.f_locals
            del frame
        elif _locs_ is None:
            _locs_ = _globs_
        exec('exec _code_ in _globs_, _locs_')

    exec_('def reraise(tp, value, tb=None):\n  raise tp, value, tb\n')

    import threading
    threading.get_ident = threading._get_ident
