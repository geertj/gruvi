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

# The logging module documents this slight hack to disable finding caller
# information (via sys._getframe()) for every logging call. In our logger we
# only get logging information if needed (at the DEBUG level or higher), so we
# can disable collecting it for every call.
logging._srcfile = None


def get_logger(context=None, name=None):
    """Return a logger for *context*.

    Return a :class:`ContextLogger` instance. The instance implements the
    standard library's :class:`logging.Logger` interface.
    """
    # Many class instances have their own logger. Share them to save memory if
    # possible, i.e. when *context* is not set.
    if name is None:
        name = _logger_name
    if context is None and name in _logger_dict:
        return _logger_dict[name]
    if context is not None and not isinstance(context, six.string_types):
        context = util.objref(context)
    logger = logging.getLogger(name)
    logger = ContextLogger(logger, context)
    if context is None:
        _logger_dict[name] = logger
    return logger


class ContextLogger(object):
    """A logger adapter that prepends a context string to log messages.

    It also supports passing arguments via '{}' format operations.
    """

    __slots__ = ('_logger', '_context')

    # This is not based on logging.LoggingAdapter because the 2.x and 3.x
    # implementations differ quite a bit, which means we would need to
    # reimplement almost the entire thing anyway.

    def __init__(self, logger, context=None):
        self._logger = logger
        self._context = context or ''

    @property
    def context(self):
        """Return the logging context."""
        return self._context

    def thread_info(self):
        """Return a string identifying the current thread and fiber."""
        tid = threading.current_thread().name
        if tid == 'MainThread':
            tid = 'Main'
        current = fibers.current()
        fid = getattr(current, 'name', util.objref(current)) if current.parent else 'Root'
        return '{}/{}'.format(tid, fid)

    def frame_info(self):
        """Return a string identifying the current frame."""
        if not self._logger.isEnabledFor(logging.DEBUG):
            return ''
        f = sys._getframe(3)
        fname = os.path.split(f.f_code.co_filename)[1]
        return '{}:{}'.format(fname, f.f_lineno)

    def log(self, level, msg, *args, **kwargs):
        if not self._logger.isEnabledFor(level):
            return
        prefix = '{}|{}|{}'.format(self.thread_info(), self.context or '-', self.frame_info())
        if args:
            msg = msg.format(*args)
        msg = '[{}] {}'.format(prefix, msg)
        self._logger._log(level, msg, (), **kwargs)

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
