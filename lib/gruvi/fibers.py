#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import fibers

from . import logging
from .hub import get_hub, switchpoint
from .sync import Event
from .errors import Cancelled, Timeout
from .callbacks import add_callback, remove_callback, run_callbacks

__all__ = ['current_fiber', 'Fiber', 'spawn']


def current_fiber():
    """Return the current fiber.

    Note: The root and hub fiber are "bare" :class:`fibers.Fiber` instances.
    Calling this method there returns the bare instance, not a
    :class:`gruvi.Fiber` instance.
    """
    return fibers.current()


class Fiber(fibers.Fiber):
    """An cooperatively scheduled execution context aka *green thread* aka
    *co-routine*."""

    # This class is a very thin layer on top of fibers.Fiber. It adds a start()
    # method that schedules a switch via the hub. It also enforces that only
    # the hub may call switch().
    #
    # All user created fibers should use this interface. The only fibers in a
    # Gruvi application that use the "raw" interface from the fibers package
    # are the root fiber and the Hub.

    __slots__ = ('_name', 'context', '_target', '_log', '_done', '_callbacks')

    def __init__(self, target, args=(), kwargs={}, name=None, hub=None):
        """
        The *target* argument is the main function of the fiber. It must be a
        Python callable. The *args* and *kwargs* specify its arguments and
        keyword arguments, respectively.

        The *name* argument specifies the fiber name. This is purely a
        diagnositic tool is used e.g. in log messages.

        The *hub* argument can be used to override the hub that will be used to
        schedule this fiber. This argument is used by the unit tests and should
        not by needed.
        """
        self._hub = hub or get_hub()
        super(Fiber, self).__init__(self.run, args, kwargs, self._hub)
        if name is None:
            fid = self._hub.data.setdefault('gruvi:next_fiber', 1)
            name = 'Fiber-{}'.format(fid)
            self._hub.data['gruvi:next_fiber'] += 1
        self._name = name
        self._target = target
        self._log = logging.get_logger()
        self._done = Event()
        self._callbacks = None

    @property
    def name(self):
        """The fiber's name."""
        return self._name

    @property
    def alive(self):
        """Whether the fiber is alive."""
        return self.is_alive()

    def start(self):
        """Schedule the fiber to be started in the next iteration of the
        event loop."""
        target = getattr(self._target, '__qualname__', self._target.__name__)
        self._log.debug('starting fiber {}, target {}', self.name, target)
        self._hub.run_callback(self.switch)

    def switch(self, value=None):
        # Only the hub may call this.
        if self.current() is not self._hub:
            raise RuntimeError('only the Hub may switch() to a fiber')
        if not self.is_alive():
            self._log.warning('attempt to switch to a dead Fiber')
            return
        return super(Fiber, self).switch(value)

    def throw(self, typ, val=None, tb=None):
        # Only the hub may call this.
        if self.current() is not self._hub:
            raise RuntimeError('only the Hub may throw() into a fiber')
        return super(Fiber, self).throw(typ, val, tb)

    def cancel(self, message=None):
        """Schedule the fiber to be cancelled in the next iteration of the
        event loop.

        Cancellation works by throwing a :class:`~gruvi.Cancelled` exception
        into the fiber. If *message* is provided, it will be set as the value
        of the exception.
        """
        if not self.is_alive():
            return
        if message is None:
            message = 'cancelled by Fiber.cancel()'
        self._hub.run_callback(self.throw, Cancelled, Cancelled(message))

    @switchpoint
    def join(self, timeout=None):
        """Wait until the fiber completes."""
        if not self._done.wait(timeout):
            raise Timeout('timeout waiting for fiber to exit')

    def run(self, *args, **kwargs):
        # Target of the first :meth:`switch()` call.
        if self.current() is not self:
            raise RuntimeError('run() may only be called from self')
        try:
            self._target(*args, **kwargs)
        except Cancelled as e:
            self._log.debug('fiber was cancelled ({!s})', e)
        except BaseException:
            self._log.exception('uncaught exception in fiber')
        self._done.set()
        run_callbacks(self)

    # Support wait()

    def add_done_callback(self, callback, *args):
        if self._done.is_set():
            callback(*args)
            return
        return add_callback(self, callback, args)

    def remove_done_callback(self, handle):
        remove_callback(self, handle)


def spawn(func, *args, **kwargs):
    """Spawn a new fiber.

    A new :class:`Fiber` is created with main function *func* and positional
    arguments *args*. The keyword arguments are passed to the :class:`Fiber`
    constructor, not to the main function. The fiber is then scheduled to start
    by calling its :meth:`~Fiber.start` method.

    The fiber instance is returned.
    """
    fiber = Fiber(func, args, **kwargs)
    fiber.start()
    return fiber
