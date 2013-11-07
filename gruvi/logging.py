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
import fibers

from . import compat

__all__ = ['get_logger']


def get_logger(context, parent=None, name='gruvi'):
    """Return a logger for *context*.

    The *parent* argument specifies an optional parent. If it is provided, the
    parent's context will be prepended to the context. The *name* argument
    specifies the name of the logger.

    Return a :cls:`ContextLogger` instance. The instance implements the
    standard library's :cls:`logging.Logger` interface.
    """
    logger = logging.getLogger(name)
    if not logger.isEnabledFor(logging.DEBUG):
        patch_logger(logger)
    return ContextLogger(logger, context, parent)


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


class ContextLogger(object):
    """A logger adapter that prepends a context string to log messages.
    
    It also supports passing arguments via '{}' format operations.
    """

    # This is not based on logging.LoggingAdapter because the 2.x and 3.x
    # implementations differ quite a bit, which means we would need to
    # reimplement almost the entire thing anyway.

    def __init__(self, logger, context, parent=None):
        self.logger = logger
        self.context = '{0}: {1}'.format(parent.context, context) \
                            if parent else context

    def log(self, level, exc, msg, *args, **kwargs):
        if not self.logger.isEnabledFor(level):
            return
        current = fibers.current()
        from .util import objref
        prefix = getattr(current, 'name', objref(current))
        if self.logger.isEnabledFor(logging.DEBUG):
            target = getattr(current, 'target', None)
            if target:
                prefix += '{0}()'.format(compat.getqualname(target))
            elif current.parent is None:
                prefix += '(root)'
            f = sys._getframe(2)
            fname = os.path.split(f.f_code.co_filename)[1]
            prefix += '@{0}:{1}:{2}'.format(fname, f.f_code.co_name, f.f_lineno)
        if self.context:
            prefix += '; {0}'.format(self.context)
        if args or kwargs:
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
