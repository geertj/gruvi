#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import collections
import fibers

from . import hub, logging, util
from .hub import switchpoint

__all__ = ['Condition', 'ConditionSet', 'Queue', 'Fiber']


class Condition(object):
    """A condition object.
    
    A difference with Python's :cls:`treading.Condition` is that version allows
    to associate a value with :meth:`notify`. Also, since we are scheduled
    cooperatively, this does not require a lock. So there are no ``acquire()``
    and ``release()`` methods.
    """

    def __init__(self):
        self._hub = hub.get_hub()
        self._waiters = []

    def notify(self, value=None):
        for notify in self._waiters:
            notify(value)
        del self._waiters[:]

    def wait(self, timeout=None):
        self._waiters.append(self._hub.switch_back())
        value = self._hub.switch(timeout)
        return value


class ConditionSet(object):
    """A set of named conditions."""

    def __init__(self):
        self._waiting = set()
        self._condition = Condition()

    def notify(self, condition, value=None):
        """Set an condition named *cond*."""
        if condition not in self._waiting:
            return False
        self._condition.notify((condition, value))
        return True

    def wait(self, *conditions, **kwargs):
        """Wait for one of *conditions* to be set."""
        timeout = kwargs.get('timeout')
        self._waiting = set(conditions)
        ret = self._condition.wait(timeout)
        assert len(ret) == 1
        if ret[0] is None:
            return  # timeout
        condition, value = ret[0]
        assert condition in self._waiting
        self._waiting.clear()
        return value


class Queue(object):
    """A synchronized queue."""

    def __init__(self, on_size_change=None, sizefunc=None):
        """Create a new queue.

        The *on_size_change* paremeter is an optional callback that will be
        called when the size of the queue changes.
        """
        self._queue = collections.deque()
        self._queue_size = 0
        self._queue_not_empty = Condition()
        self._on_size_change = on_size_change
        self._sizefunc = sizefunc or (lambda x: len(x))

    def qsize(self):
        """Return the current queue size."""
        return self._queue_size

    def _adjust_size(self, delta):
        """Adjust the queue size property."""
        oldsize = self._queue_size
        self._queue_size += delta
        if self._on_size_change:
            self._on_size_change(oldsize, self._queue_size)

    def put(self, obj):
        """Add an object *obj* to the queue."""
        self._queue.append(obj)
        self._adjust_size(self._sizefunc(obj))
        self._queue_not_empty.notify()

    @switchpoint
    def get(self, timeout=None):
        """Pop an object from the queue. Wait for up to *timeout* seconds if
        the queue is empty."""
        if not self._queue:
            self._queue_not_empty.wait(timeout)
        obj = self._queue.popleft()
        self._adjust_size(-self._sizefunc(obj))
        return obj


class Fiber(fibers.Fiber):
    """An explicitly scheduled independent execution context aka *co-routine*.

    This class is a very thin layer on top of :class:`fibers.Fiber`. It adds a
    :meth:`start` method that schedules a switch-in via the hub. It also
    enforces that only the hub may call :meth:`switch`.

    All user created fibers should use this interface. The only fibers in a
    Gruvi application that use the "raw" :class:`fiber.Fiber` interface are the
    root fiber, and the :class:`Hub`.
    """

    def __init__(self, target, args=None):
        self._hub = hub.get_hub()
        super(Fiber, self).__init__(target=self.run, parent=self._hub)
        self._target = target
        self._args = args or ()
        self._log = logging.get_logger(context=util.objref(self))
        self._done = Condition()

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
            self._log.exception('uncaught exception in fiber')
            exc = e
        self._done.notify()

    def join(self, timeout=None):
        """Wait until the the fiber exits."""
        current = self.current()
        if current is self._hub:
            raise RuntimeError('you may not join() the Hub')
        elif current.parent is None:
            raise RuntimeError('you may not join() the root fiber')
        self._done.wait(timeout)
