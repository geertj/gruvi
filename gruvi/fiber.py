#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import inspect
import fibers
from . import hub, logging, util

__all__ = ['Fiber']


class Fiber(fibers.Fiber):
    """An explicitly scheduled independent execution context aka *co-routine*.

    This class is a very thin layer on top of :class:`fibers.Fiber`. It adds a
    :meth:`start` method that schedules a switch-in via the hub, and that
    enforces that only the hub may call :meth:`swich`.

    All user created fibers should use this interface. The only fibers in a
    Gruvi application that use the "raw" :class:`fiber.Fiber` interface are the
    root fiber, and the :class:`Hub`.
    """

    def __init__(self, target, args=None):
        self._hub = hub.get_hub()
        super(Fiber, self).__init__(target=self.run, parent=self._hub)
        self._target = target
        self._args = args or ()
        self._logger = logging.get_logger(util.objref(self))
        self._callbacks = []

    @property
    def target(self):
        """The fiber's target."""
        return self._target

    def start(self):
        """Schedule the fiber to be started in the next iteration of the
        event loop."""
        self._hub.run_callback(self.switch)

    def switch(self, value=None):
        """Switch to this fiber."""
        if self.current() is not self._hub:
            raise RuntimeError('only the Hub may switch() to a fiber')
        return super(Fiber, self).switch(value)

    def run(self):
        # Target of the first :meth:`switch()` call.
        exc = None
        try:
            value = self._target(*self._args)
        except Exception as e:
            self._logger.exception('uncaught exception in fiber')
            exc = e
        for callback in self._callbacks:
            self._hub.run_callback(callback, self, value, exc)

    def notify(self, callback):
        """Notify a callback when the fiber exits."""
        self._callbacks.append(callback)

    def join(self):
        """Wait until the the fiber exits."""
        current = self.current()
        if current is self._hub:
            raise RuntimeError('you may not join() the Hub')
        if current.parent is None:
            raise RuntimeError('you may not join() the root fiber')
        self.notify(self._hub.switch_back())
        self._hub.switch(timeout)
