#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

import re
import sys
import inspect


PY3 = sys.version_info >= (3, 0, 0)
PY26 = sys.version_info[:2] <= (2,6)

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

# Support Python 2.7+ implictly indexed positional argument specifiers also on
# Python 2.6. Also remove the non-supported ',' format specifier

# {{ and }} are escape characters. Use negative lookbehind/ahead to ensure
# an odd number of braces on either side.
re_pos_arg = re.compile(r'(?<!\{)((?:\{\{)*\{)([:!][^}]+)?(\}(?:\}\})*)(?!\})')

def fixup_format_string(fmt):
    count = [0]
    def replace(mobj):
        field = str(count[0]); count[0] += 1
        spec = (mobj.group(2) or '').replace(',', '')
        return mobj.group(1) + field + spec + mobj.group(3)
    return re_pos_arg.sub(replace, fmt)
