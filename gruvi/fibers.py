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
from .hub import get_hub
from .sync import Event
from .errors import Cancelled

__all__ = ['current_fiber', 'Fiber', 'spawn']


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

    __slots__ = ('name', 'context', '_target', '_log', '_thread', '_done')

    def __init__(self, target, args=(), kwargs={}, name=None, hub=None):
        self._hub = hub or get_hub()
        super(Fiber, self).__init__(self.run, args, kwargs, self._hub)
        if name is None:
            fid = self._hub.data.setdefault('next_fiber', 1)
            name = 'Fiber-{0}'.format(fid)
            self._hub.data['next_fiber'] += 1
        self.name = name
        self.context = ''
        self._target = target
        self._log = logging.get_logger()
        self._thread = threading.current_thread()
        self._done = Event()

    def start(self):
        """Schedule the fiber to be started in the next iteration of the
        event loop."""
        target = getattr(self._target, '__qualname__', self._target.__name__)
        self._log.debug('starting fiber {}, target {}', self.name, target)
        self._hub.run_callback(self.switch)

    def switch(self, value=None):
        """Switch to this fiber."""
        if self.current() is not self._hub:
            raise RuntimeError('only the Hub may switch() to a fiber')
        if threading.current_thread() is not self._thread:
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
            return
        self._hub.run_callback(self.throw, Cancelled('cancelled by Fiber.cancel()'))

    def join(self, timeout=None):
        """Wait until the fiber completes."""
        self._done.wait(timeout)

    def run(self, *args, **kwargs):
        # Target of the first :meth:`switch()` call.
        if self.current() is not self:
            raise RuntimeError('run() may only be called from self')
        try:
            self._target(*args, **kwargs)
        except Cancelled as e:
            self._log.debug(str(e))
        except Exception:
            self._log.exception('uncaught exception in fiber')
        self._done.set()


def spawn(func, *args, **kwargs):
    """Spawn function *func* in a separate greenlet."""
    fiber = Fiber(func, args, kwargs)
    fiber.start()
    return fiber
