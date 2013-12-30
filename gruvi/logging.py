#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import logging
import threading
import fibers
import re

from . import compat

__all__ = ['get_logger']


def get_logger(context, name='gruvi'):
    """Return a logger for *context*.

    Return a :class:`ContextLogger` instance. The instance implements the
    standard library's :class:`logging.Logger` interface.
    """
    if not isinstance(context, compat.string_types):
        from .util import objref
        context = objref(context)
    logger = logging.getLogger(name)
    if not logger.isEnabledFor(logging.DEBUG):
        patch_logger(logger)
    return ContextLogger(logger, context)


def patch_logger(logger):
    """Replace the ``findCaller()`` method of *logger* with a nop.

    This method uses :func:`sys._getframe` to look up the name and line number
    of its caller, causing a huge slowdown on PyPy.
    
    This function is used when debugging is not enabled.
    """
    if logger.findCaller is not logging.Logger.findCaller:
        return
    def findCaller(self, stack_info=False):
        return ('(unknown file)', 0, '(unknown function)', None)
    logger.findCaller = findCaller


# Support Python 2.7+ implictly indexed format strings also on Python 2.6

PY26 = sys.version_info[:2] <= (2,6)
# {{ and }} are escape characters. Use negative lookbehind/ahead to ensure
# an odd number of braces on either side.
re_fmt = re.compile(r'(?<!\{)((?:\{\{)*\{)([:!][^}]+)?(\}(?:\}\})*)(?!\})')

def replace_fmt(msg):
    count = [0]
    def replace(mobj):
        replaced = mobj.group(1) + str(count[0]) + (mobj.group(2) or '') + mobj.group(3)
        count[0] += 1
        return replaced
    return re_fmt.sub(replace, msg)


class ContextLogger(object):
    """A logger adapter that prepends a context string to log messages.
    
    It also supports passing arguments via '{}' format operations.
    """

    # This is not based on logging.LoggingAdapter because the 2.x and 3.x
    # implementations differ quite a bit, which means we would need to
    # reimplement almost the entire thing anyway.

    def __init__(self, logger, context):
        self.logger = logger
        self.context = context

    def thread_info(self):
        from .util import objref
        tid = objref(threading.current_thread())
        current = fibers.current()
        if current.parent or hasattr(current, 'loop'):
            fid = objref(current)
        else:
            fid = '(root)'
        return '{0}:{1}'.format(tid, fid)

    def stack_info(self):
        f = sys._getframe(3)
        fname = os.path.split(f.f_code.co_filename)[1]
        funcname = f.f_code.co_name
        return '{0}:{1}()#L{2} '.format(fname, funcname, f.f_lineno)

    def log(self, level, exc, msg, *args, **kwargs):
        if not self.logger.isEnabledFor(level):
            return
        prefix = ''
        if self.logger.isEnabledFor(logging.DEBUG):
            parts = [self.thread_info(), self.stack_info()]
            prefix += '@'.join(filter(None, parts))
        if self.context:
            prefix += self.context
        if args or kwargs:
            if PY26:
                msg = replace_fmt(msg)
            msg = msg.format(*args, **kwargs)
        msg = '[{0}] {1}'.format(prefix, msg)
        self.logger._log(level, msg, (), exc_info=exc)

    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, False, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, False, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.log(logging.WARNING, False, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.log(logging.ERROR, False, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.log(logging.CRITICAL, False, msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self.log(logging.ERROR, True, msg, *args, **kwargs)
