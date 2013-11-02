#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import fibers
import logging
from . import util, compat


# get_logger() / LoggingLogger() implement a small indirection on top of the
# stdlib's logging implementation. It exists for a number of reasons:
#
# - It is used to prefix log messages with a common piece of context. This
#   prevents us from having to write really long log messages every time.
# - It allows us in the future to experiment with other logging modules.

def get_logger(context):
    """Return a logger for *context*. The instance that is returned implements
    the standard library's ``logging.Logger`` interface.
    """
    return LoggingLogger(context)


class LoggingLogger(object):
    """Forward log messages to the Python logging system."""

    _patched_logger = False

    def __init__(self, context):
        self.context = context
        self.logger = logging.getLogger('gruvi')
        self._patch_logger()

    def _patch_logger(self):
        # Patch Logger.findCaller() so that it becomes a no-op. Finding out the
        # caller uses sys._getframe() which is a huge slowdown on PyPy. We make
        # sure that log messages are clear without identifying our caller.
        if self._patched_logger:
            return
        self.logger.findCaller = lambda *args: \
                        ('(unknown file)', 0, '(unknown function)')
        type(self)._patched_logger = True

    def _process(self, msg, args, kwargs):
        current = fibers.current()
        grname = getattr(current, 'name', util.objref(current))
        target = getattr(current, 'target', None)
        if target:
            target = compat.getqualname(target)
            grname = '{0}({1})'.format(grname, target)
        prefix = '{0}: {1}'.format(grname, self.context)
        if args or kwargs:
            msg = msg.format(*args, **kwargs)
        msg = '[{0}] {1}'.format(prefix, msg)
        return msg

    def debug(self, msg, *args, **kwargs):
        msg = self._process(msg, args, kwargs)
        self.logger.debug(msg)

    def info(self, msg, *args, **kwargs):
        msg = self._process(msg, args, kwargs)
        self.logger.info(msg)

    def warning(self, msg, *args, **kwargs):
        msg = self._process(msg, args, kwargs)
        self.logger.warning(msg)

    def error(self, msg, *args, **kwargs):
        msg = self._process(msg, args, kwargs)
        self.logger.error(msg)

    def exception(self, msg, *args, **kwargs):
        msg = self._process(msg, args, kwargs)
        self.logger.exception(msg)
