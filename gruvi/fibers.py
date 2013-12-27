#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import fibers
import threading

from . import logging
from .hub import get_hub, switchpoint
from .sync import Signal, Queue
from .error import Cancelled

__all__ = ['current_fiber', 'Fiber']


def current_fiber():
    """Return the current fiber."""
    return fibers.current()


class Fiber(fibers.Fiber):
    """An explicitly scheduled execution context aka *co-routine*.

    This class is a very thin layer on top of :class:`fibers.Fiber`. It adds a
    :meth:`start` method that schedules a switch via the hub. It also enforces
    that only the hub may call :meth:`switch`.

    All user created fibers should use this interface. The only fibers in a
    Gruvi application that use the "raw" interface from the :class:`fibers`
    package are the root fiber and the :class:`Hub`.
    """

    def __init__(self, target, args=(), kwargs={}):
        self._hub = get_hub()
        super(Fiber, self).__init__(self.run, args, kwargs, self._hub)
        self._target = target
        self._log = logging.get_logger(self)
        self._done = Signal()
        self._thread = threading.get_ident()

    @property
    def done(self):
        """Signal that is raised when the fiber exits.

        Signal arguments: ``(return_value, exc)``.
        """
        return self._done

    @property
    def alive(self):
        """Returns wether the file is alive."""
        return self.is_alive()

    def start(self):
        """Schedule the fiber to be started in the next iteration of the
        event loop."""
        self._log.debug('starting fiber, target = {!s}', self._target)
        self._hub.run_callback(self.switch)

    def switch(self, value=None):
        """Switch to this fiber."""
        if self.current() is not self._hub:
            raise RuntimeError('only the Hub may switch() to a fiber')
        if threading.get_ident() != self._thread:
            raise RuntimeError('cannot switch from different thread')
        if not self.is_alive():
            self._log.warning('attempt to switch to a dead Fiber')
            return
        return super(Fiber, self).switch(value)

    def cancel(self):
        """Cancel this fiber.
        
        The fiber is cancelled by throwing a :class:`Cancelled` exception
        inside it.
        """
        if not self.is_alive():
            self._log.warning('attempt to cancel an already dead Fiber')
            return
        self.throw(Cancelled('cancelled by Fiber.cancel()'))

    def run(self, *args, **kwargs):
        # Target of the first :meth:`switch()` call.
        if self.current() is not self:
            raise RuntimeError('run() may only be called from self')
        value = exc = None
        try:
            value = self._target(*args, **kwargs)
        except Exception as e:
            self._log.exception('uncaught exception in fiber')
            exc = e
        self.done.emit(value, exc)
