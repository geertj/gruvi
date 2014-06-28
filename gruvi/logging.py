#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import logging
import threading
import fibers
import six

from . import util, compat

__all__ = ['get_logger']


_logger_name = 'gruvi'
_logger_dict = {}

def get_logger(context='', name=None):
    """Return a logger for *context*.

    Return a :class:`ContextLogger` instance. The instance implements the
    standard library's :class:`logging.Logger` interface.
    """
    if name is None:
        name = _logger_name
    # To save memory, return a singleton instance for loggers without context.
    if not context:
        logger = _logger_dict.get(name)
        if logger is not None:
            return logger
    elif not isinstance(context, six.string_types):
        context = util.objref(context)
    logger = logging.getLogger(name)
    patch_logger(logger)
    logger = ContextLogger(logger, context)
    if not context:
        _logger_dict[name] = logger
    return logger


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

    __slots__ = ('logger', 'context')

    # This is not based on logging.LoggingAdapter because the 2.x and 3.x
    # implementations differ quite a bit, which means we would need to
    # reimplement almost the entire thing anyway.

    def __init__(self, logger, context=''):
        self.logger = logger
        self.context = context

    def thread_info(self):
        tid = threading.current_thread().name
        if tid == 'MainThread':
            tid = 'Main'
        current = fibers.current()
        fid = getattr(current, 'name', util.objref(current)) if current.parent else 'Root'
        return '{0}:{1}'.format(tid, fid)

    def context_info(self):
        log_context = self.context
        fiber_context = getattr(fibers.current(), 'context', '')
        if not fiber_context:
            return log_context
        return '{0}:{1}'.format(log_context, fiber_context)

    def stack_info(self):
        if not self.logger.isEnabledFor(logging.DEBUG):
            return ''
        f = sys._getframe(3)
        fname = os.path.split(f.f_code.co_filename)[1]
        funcname = f.f_code.co_name
        return '{0}:{1}!{2}()'.format(fname, f.f_lineno, funcname)

    def log(self, level, exc, msg, *args, **kwargs):
        if not self.logger.isEnabledFor(level):
            return
        prefix = [self.thread_info(), self.context_info(), self.stack_info()]
        while not prefix[-1]:
            prefix.pop()
        prefix = '|'.join(prefix)
        if args or kwargs:
            msg = compat.fixup_format_string(msg)
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
