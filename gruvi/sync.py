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
import collections
import heapq

from . import logging, util, local
from .hub import switchpoint, get_hub, switch_back
from .error import Cancelled

__all__ = ['Lock', 'Signal', 'Queue', 'current_signal', 'wait', 'waitall']


class Lock(object):
    """A lock object.

    The lock is acquired using :meth:`acquire` and released using
    :meth:`release`. A lock can also be used as a context manager.

    This lock is thread safe.
    """

    def __init__(self, recursive=False):
        self._recursive = recursive
        self._lock = threading.Lock()
        self._locked = False
        self._owner = None
        self._waiters = collections.deque()

    @property
    def locked(self):
        return self._locked

    @switchpoint
    def acquire(self, timeout=None):
        """Acquire the lock.
        
        The *timeout* parameter specifies an optional timeout in seconds. The
        return value is a boolean indicating whether the lock was acquired.
        """
        hub = get_hub()
        if timeout is not None:
            end_time = hub.loop.now() + timeout
        while True:
            with switch_back(timeout) as switcher:
                with self._lock:
                    if not self._locked:
                        self._locked = 1
                        self._owner = fibers.current()
                        return True
                    elif self._owner is fibers.current():
                        if not self._recursive:
                            raise RuntimeError('already locked by this fiber')
                        self._locked += 1
                        return True
                    self._waiters.append(switcher)
                if timeout is not None:
                    timeout = end_time - hub.loop.now()
                # It is safe to call hub.switch() outside the lock. Another
                # thread could have called acquire()+release(), thereby firing
                # the switchback. However the switchback only schedules the
                # switchback in our hub, it won't execute it yet. So the
                # switchback won't actually happen until we switch to the hub.
                hub.switch()
        return False

    def release(self):
        """Release the lock."""
        with self._lock:
            if not self._locked:
                raise RuntimeError('lock not currently held')
            self._locked -= 1
            if not self._locked:
                self._owner = None
            if not self._waiters:
                return
            notify = self._waiters.popleft()
            notify()

    __enter__ = acquire
    __exit__ = lambda self,*exc_info: self.release()


def current_signal():
    """Return the signal that is currently being raised, if any.

    This is equivalent to :meth:`Signal.current_signal`.
    """
    return Signal.current_signal()


class Signal(object):
    """A signal object.
    
    A signal is a synchronization primitive that allows one or more fibers to
    wait for an event to happen. A signal can be emitted using :meth:`emit`,
    and be waited for using :meth:`wait`. You can also connect a callback to
    the signal using :meth:`connect`.

    Positional arguments that are provided when the signal is emitted will be
    passed on as the return value of :meth:`wait`.

    A signal is thread safe. To synchronize calls between :meth:`emit` and
    :meth:`wait` across multiple threads, acquire the :attr:`lock` before
    calling either function.

    Note that a signal is edge triggered. This means that only those fibers are
    notified that are waiting at the moment the signal is emitted. Immediateley
    after the signal is emitted, it is reset, and the signal arguments are
    lost. In this respect, a signal is similar to a :class:`threading.Condition`
    (albeit with arguments).
    """

    def __init__(self, lock=None):
        self._log = logging.get_logger(util.objref(self))
        self._lock = lock or Lock()
        self._callbacks = collections.deque()

    @property
    def lock(self):
        """The signal's lock.
        
        Acquiring this lock before calling :meth:`emit` and :meth:`wait` allows
        you to synchronize these calls across multiple threads.
        """
        return self._lock

    _local = local.local()

    @classmethod
    def current_signal(cls):
        """Return the currrent signal, if any.

        This method will only return a value inside a signal callback. In all
        other cases, this will return ``None``.
        """
        return getattr(cls._local, 'signal', None)

    @property
    def callbacks(self):
        """Return the currently registered callbacks."""
        return [cb[0].callback for cb in self._callbacks if hasattr(cb[0], 'callback')]

    @property
    def waiters(self):
        """Return the fibers currently waiting on this signal."""
        return [cb[0].fiber for cb in self._callbacks if hasattr(cb[0], 'fiber')]

    def emit(self, *args):
        """Emit the signal.

        Any positional argument passed here will be returned by :meth:`wait`.
        """
        for i in range(len(self._callbacks)):
            callback, waitfor, rearm = self._callbacks.popleft()
            if isinstance(waitfor, tuple):
                match = args and args[0] in waitfor
            elif callable(waitfor):
                match = waitfor(*args)
            else:
                match = True
            if match:
                try:
                    callback(*args)
                except Cancelled:
                    rearm = False
                except Exception as e:
                    self._log.exception('Uncaught exception in callback')
            if rearm or not match:
                self._callbacks.append((callback, waitfor, rearm))

    @switchpoint
    def wait(self, timeout=None, waitfor=None):
        """Wait for the signal to be emitted.

        The optional *timeout* argument specifies the number of seconds to
        wait. If no timeout is provided, then this method waits indefinitely.

        The optional *waitfor* argument can be used to wait for specific values
        of the signal arguments. It can be a tuple of values, in which case the
        first signal argument must be in the tuple. It may also be a callable
        that takes the signal arguments as parameters and returns a boolean
        indicating if the caller wants to wait for this signal.

        If the :attr:`lock` is held when this method is called, then it will be
        released after the current fiber blocks, and acquired again before this
        method returns. This allows you to synchronize :meth:`wait` and
        :meth:`emit` between each other in a multi-threaded environment.

        The return value is a tuple containing the positional arguments passed
        to :meth:`emit`.
        """
        hub = get_hub()
        lock_count = self.lock.locked
        unlocked = False
        try:
            with switch_back(timeout) as switcher:
                self._callbacks.append((switcher, waitfor, False))
                # See the comment in Lock.acquire() why it is OK to release the
                # lock here before calling hub.switch().
                # Also if this is a recursive lock make sure it is fully released.
                if lock_count:
                    self.lock._locked = 1
                    self.lock.release()
                    unlocked = True
                result = hub.switch()
        finally:
            if unlocked:
                self.lock.acquire()
                self.lock._locked = lock_count
        return result[0]

    def connect(self, callback):
        """Connect a callback to the signal.

        The callback will be called every time the signal is emitted. It will
        be called as ``callback(*args)`` with ``*args`` the arguments passed to
        :meth:`emit`.

        Callbacks are always run in the Hub of the thread that called this
        method.
        """
        hub = get_hub()
        def schedule_callback(*args):
            def call_callback():
                self._local.signal = self
                try:
                    callback(*args)
                finally:
                    self._local.signal = None
            hub.run_callback(call_callback)
        schedule_callback.callback = callback
        self._callbacks.append((schedule_callback, None, True))

    def disconnect(self, callback):
        """Disconnect a callback."""
        # Keep the order of the callbacks. And optimize for the case when you
        # disconnect a signal that was recently connected (e.g. wait()).
        pos = 0
        for cb in reversed(self._callbacks):
            if cb[0].callback is callback:
                break
            pos += 1
        else:
            return
        self._callbacks.rotate(pos)
        self._callbacks.pop()
        self._callbacks.rotate(-pos)


class Queue(object):
    """A synchronized priority queue.

    Items are pushed onto the queue with :meth:`push` and popped with
    :meth:`pop`. The latter will pop the item with the highest priority, which
    by default will be the item with the highest age (i.e. a FIFO queue).

    A queue is thread safe. To synchronize calls between :meth:`put` and
    :meth:`get` in different threads, acquire the :attr:`lock` before calling
    either method.
    """

    def __init__(self, sizefunc=None, priofunc=None):
        """The optional *sizefunc* paremeter can be used to define a custom
        size for queue elements. It must be a function that takes a queue
        element as its argument, and returns its size. If no *sizefunc* is
        provided, then all elements will have a size of 1. In this case,
        ``len(queue)`` wil be equal to the queue :meth:`size`.

        The optional *priofunc* can be used to specify a priority for queue
        elements. It must be a function that takes a queue element as its
        argument, and returns its priority. The priority must be an integer,
        with higher values meaning higher priorities. If no *priofunc* is
        provided, then the priority of an item will be its age.
        """
        self._heap = []
        self._size = 0
        self._sizefunc = sizefunc or (lambda x: 1)
        if priofunc is None:
            self._counter = 0
            def priofunc(x):
                self._counter -= 1
                return self._counter
        self._priofunc = priofunc
        self._size_changed = Signal()

    @property
    def lock(self):
        """The queue's lock.
        
        Acquiring this lock before calling :meth:`put` and :meth:`get` allows
        you to synchronize these calls across multiple threads.
        """
        return self._size_changed._lock

    @property
    def size_changed(self):
        """A signal that is emitted when the size of the queue has changed.
        
        Signal arguments: ``size_changed(oldsize, newsize)``.
        """
        return self._size_changed

    def _adjust_size(self, delta):
        """Adjust the queue size by some value in case one of the queue
        elements changed size on the fly."""
        oldsize, self._size = self._size, self._size+delta
        self.size_changed.emit(oldsize, self._size)

    def __len__(self):
        """Return the number of items in the queue."""
        return len(self._heap)

    def size(self):
        """Return the size of the queue."""
        return self._size

    def put(self, obj):
        """Push an object onto the queue."""
        prio = self._priofunc(obj)
        heapq.heappush(self._heap, (-prio, obj))
        self._adjust_size(self._sizefunc(obj))

    @switchpoint
    def get(self, timeout=None):
        """Pop the object with the highest priority from the queue.
        
        If the queue is empty, wait up to *timeout* seconds until an item
        becomes available. If the timeout is not provided, then wait
        indefinitely. On timeout, a :class:`Timeout` exception is raised.
        """
        while len(self._heap) == 0:
            self.size_changed.wait(timeout)
        prio, obj = heapq.heappop(self._heap)
        self._adjust_size(-self._sizefunc(obj))
        return obj


@switchpoint
def wait(signals, timeout=None):
    """Wait for one of the signals to be raised.

    The optional *timeout* keyword argument can be provided to specify a timeout.
    
    Return a tuple containing the signal followed by its arguments.
    """
    raised = Signal()
    def callback(*args):
        raised.emit(current_signal(), *args)
    for signal in signals:
        signal.connect(callback)
    try:
        result = raised.wait(timeout)
    finally:
        for signal in signals:
            signal.disconnect(callback)
    return result


@switchpoint
def waitall(signals, **kwargs):
    """Wait for all of *signals* to be raised.
    
    An optional *timeout* keyword argument can be provided to specify a timeout.

    Returns an iterator that yields tuples containing the signal followed by
    its arguments.
    """
    raised = Queue()
    timeout = kwargs.get('timeout')
    hub = get_hub()
    def callback(*args):
        raised.put((current_signal(),) + args)
    active = set()
    for signal in signals:
        signal.connect(callback)
        active.add(signal)
    if timeout is not None:
        end_time = hub.loop.now() + timeout
    try:
        while active:
            if timeout is not None:
                timeout = max(0, end_time - hub.loop.now())
            result = raised.get(timeout)
            result[0].disconnect(callback)
            # report each signal only once
            if result[0] not in active:
                continue
            active.remove(result[0])
            yield result
    finally:
        # Most likely a Timeout but could also be a GeneratorExit
        for signal in active:
            signal.disconnect(callback)
