#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import re
import inspect
import ast
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


def wrap(template, func, globs=None, depth=1, ismethod=False):
    """Wrap a function or method.

    This is similar to :func:`functools.wraps` but rather than using a closure
    this compiles a new function using compile(). The advantage is that it
    allows sphinx autodoc to document the arguments. Without this, a generic
    wrapper would need to have a signature of ``func(*args, **kwargs)`` and
    would show up as such in the documentation.

    The *template* argument is a string containing the wrapper template. The
    template should be a valid function definition. It is passed through
    format() with the following keywoard arguments before compilation:

      * {name} - the function name
      * {signature} - function signature including parens and default values
      * {arglist} - function argument list, including parens, no default values
      * {docstring} - docstring

    The *globs* argument specifies global variables accessible to the wrapper.

    If *depth* is given, file and line numbers are tweaked so that the
    generated function appears to be in the file and on the (single) line
    of the frame at this depth.
    """
    name = func.__name__
    doc = func.__doc__ or ''
    if globs is None:
        globs = {}
    argspec = inspect.getargspec(func)
    signature = inspect.formatargspec(*argspec)
    if ismethod:
        arglist = inspect.formatargspec(argspec[0][1:], *argspec[1:], formatvalue=lambda x: '')
    else:
        arglist = inspect.formatargspec(*argspec, formatvalue=lambda x: '')
    funcdef = template.format(name=name, signature=signature, docstring=doc, arglist=arglist)
    node = ast.parse(funcdef)
    # If "depth" is provided, make the generated code appear to be on a single
    # line in the file of the frame at this depth. This makes backtraces more
    # readable.
    if depth > 0:
        frame = sys._getframe(depth)
        fname = frame.f_code.co_filename
        lineno = frame.f_lineno
        for child in ast.walk(node):
            if 'lineno' in child._attributes:
                child.lineno = lineno
            if 'col_offset' in child._attributes:
                child.col_offset = 0
    else:
        fname = '<wrap>'
    code = compile(node, fname, 'exec')
    six.exec_(code, globs)
    return globs[name]
