#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import logging
import threading
import fibers
import six

from . import util

__all__ = ['get_logger']

# Add a new level: TRACE.
logging.TRACE = 5
assert logging.NOTSET < logging.TRACE < logging.DEBUG
logging.addLevelName('TRACE', logging.TRACE)

_logger_name = 'gruvi'
_logger_dict = {}

# Method used by patch_logger() to runtime patch our logger
if six.PY2:
    def _dummy_find_caller(*ignored):
        return ('(unknown file)', 0, '(unknown function)')
else:
    def _dummy_find_caller(*ignored):
        return ('(unknown file)', 0, '(unknown function)', None)


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
    # The Logger.findCaller() is used by the various logging methods to find
    # out the function name and line number of our caller.
    # Since our logging adapter has a way to print out caller information *if
    # and only if* debugging is enabled, we don't need this information, and
    # therefore we patch out this funtion with an no-op.
    # The benefit is that if and when we support PyPy, we don't have the
    # slowdown.
    logger.findCaller = _dummy_find_caller
    logger = ContextLogger(logger, context)
    if not context:
        _logger_dict[name] = logger
    return logger


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
        return '{}:{}'.format(tid, fid)

    def context_info(self):
        log_context = self.context
        fiber_context = getattr(fibers.current(), 'context', '')
        if not fiber_context:
            return log_context
        return '{}:{}'.format(log_context, fiber_context)

    def stack_info(self):
        if not self.logger.isEnabledFor(logging.DEBUG):
            return ''
        f = sys._getframe(3)
        fname = os.path.split(f.f_code.co_filename)[1]
        funcname = f.f_code.co_name
        return '{}:{}!{}()'.format(fname, f.f_lineno, funcname)

    def log(self, level, msg, *args, **kwargs):
        if not self.logger.isEnabledFor(level):
            return
        prefix = [self.thread_info(), self.context_info(), self.stack_info()]
        while not prefix[-1]:
            prefix.pop()
        prefix = '|'.join(prefix)
        if args:
            msg = msg.format(*args)
        msg = '[{}] {}'.format(prefix, msg)
        self.logger._log(level, msg, (), **kwargs)

    def trace(self, msg, *args, **kwargs):
        self.log(logging.TRACE, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        kwargs['exc_info'] = True
        self.log(logging.ERROR, msg, *args, **kwargs)
