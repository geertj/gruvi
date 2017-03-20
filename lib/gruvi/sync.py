#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import fibers
import threading
import heapq

from .hub import switchpoint, get_hub, switch_back, assert_no_switchpoints
from .callbacks import add_callback, remove_callback, pop_callback
from .callbacks import run_callbacks, walk_callbacks

__all__ = ['Lock', 'RLock', 'Event', 'Condition', 'QueueEmpty', 'QueueFull',
           'Queue', 'LifoQueue', 'PriorityQueue']


# All primitives in this module a thread safe!


class _Lock(object):
    """Base class for regular and reentrant locks."""

    __slots__ = ('_reentrant', '_lock', '_locked', '_owner', '_callbacks')

    def __init__(self, reentrant):
        # Allocate a new lock
        self._reentrant = reentrant
        self._lock = threading.Lock()
        self._locked = 0
        self._owner = None
        self._callbacks = None

    def locked(self):
        """Whether the lock is currently locked."""
        return self._locked

    @switchpoint
    def acquire(self, blocking=True, timeout=None):
        """Acquire the lock.

        If *blocking* is true (the default), then this will block until the
        lock can be acquired. The *timeout* parameter specifies an optional
        timeout in seconds.

        The return value is a boolean indicating whether the lock was acquired.
        """
        hub = get_hub()
        try:
            # switcher.__call__ needs to be synchronized with a lock IF it can
            # be called from different threads. This is the case here because
            # this method may be called from multiple threads and the callbacks
            # are run in the calling thread. So pass it our _lock.
            with switch_back(timeout, lock=self._lock) as switcher:
                with self._lock:
                    if not self._locked:
                        self._locked = 1
                        self._owner = fibers.current()
                        return True
                    elif self._reentrant and self._owner is fibers.current():
                        self._locked += 1
                        return True
                    elif not blocking:
                        return False
                    handle = add_callback(self, switcher)
                # It is safe to call hub.switch() outside the lock. Another
                # thread could have called acquire()+release(), thereby firing
                # the switchback. However the switchback only schedules the
                # switchback in our hub, it won't execute it yet. So the
                # switchback won't actually happen until we switch to the hub.
                hub.switch()
                # Here the lock should be ours because _release() wakes up only
                # the fiber that it passed the lock.
                assert self._locked > 0
                assert self._owner is fibers.current()
        except BaseException as e:
            # Likely a Timeout but could also be e.g. Cancelled
            with self._lock:
                # Clean up the callback. It might have been popped by
                # _release() but that is OK.
                remove_callback(self, handle)
                # This fiber was passed the lock but before that an exception
                # was already scheduled with run_callback() (likely through
                # Fiber.throw())
                if self._owner is fibers.current():
                    self._release()
            if e is switcher.timeout:
                return False
            raise
        return True

    def _release(self):
        # Low-level release. Lock must be held.
        if self._locked > 1:
            self._locked -= 1
            return
        while self._callbacks:
            switcher, _ = pop_callback(self)
            if switcher.active:
                self._owner = switcher.fiber
                switcher.switch()
                return
        self._owner = None
        self._locked = 0

    def release(self):
        """Release the lock."""
        with self._lock:
            if not self._locked:
                raise RuntimeError('lock not currently held')
            elif self._reentrant and self._owner is not fibers.current():
                raise RuntimeError('lock not owned by this fiber')
            self._release()

    __enter__ = acquire
    __exit__ = lambda self, *exc_info: self.release()

    # Internal API used by Condition instances.

    def _acquire_restore(self, state):
        # Acquire a lock and restore the owner and lock count.
        self.acquire()
        self._owner, self._locked = state

    def _release_save(self):
        # Release a lock even if it is locked multiple times. Return the state.
        state = self._owner, self._locked
        self.release()
        return state


class Lock(_Lock):
    """A lock.

    The lock can be locked and unlocked explicitly using :meth:`acquire` and
    :meth:`release`, and it can also be used as a context manager.
    """

    __slots__ = _Lock.__slots__

    def __init__(self):
        super(Lock, self).__init__(False)


class RLock(_Lock):
    """A reentrant lock.

    A reentrant lock has the notion of a "lock owner" and a "lock count". If a
    reentrant lock is acquired, and it was already acquired by the current
    fiber, then the lock count is increased and the acquire call will be
    successful. Unlocking a reentrant lock may only be done by the lock owner.
    The lock becomes unlocked only after it is released as many times as it was
    acquired.
    """

    __slots__ = _Lock.__slots__

    def __init__(self):
        super(RLock, self).__init__(True)


# A few words on the use of fiber locks (Lock) vs thread locks (threading.Lock)
# in the code below.
#
# There is no difference between both locks from a safety point of view. Both
# locks are thread-safe (which implies they are fiber-safe as well). The
# difference is who gets blocked when trying to acquire a lock that is already
# locked. With a fiber lock only the current fiber is blocked and other fibers
# in current thread can continue (and fibers in other threads as well, of
# course). With a thread lock the entire current thread is blocked including
# all its fibers.
#
# This means that if we never call hub.switch() when a lock is held, fiber and
# thread locks are completely identical. In this case there's a benefit in
# using thread locks because i) they are smaller and faster, and ii) it makes
# it possible for non-switchpoints to acquire the lock. An example of the
# latter case is Queue.put_nowait().


class Event(object):
    """An event.

    An event contains an internal flag that is initially False. The flag can be
    set using the :meth:`set` method and cleared using the :meth:`clear`
    method.  Fibers can wait for the flag to become set using :meth:`wait`.

    Events are level triggered, meaning that the condition set by :meth:`set`
    is "sticky". Setting the event will unblock all current waiters and will
    cause future calls to :meth:`wait` not to block, until :meth:`clear` is
    called again.
    """

    __slots__ = ('_flag', '_lock', '_callbacks')

    def __init__(self):
        self._flag = False
        self._lock = threading.Lock()
        self._callbacks = None

    def is_set(self):
        return self._flag

    def set(self):
        """Set the internal flag, and wake up any fibers blocked on :meth:`wait`."""
        with self._lock:
            if self._flag:
                return
            self._flag = True
            with assert_no_switchpoints():
                run_callbacks(self)

    def clear(self):
        """Clear the internal flag."""
        with self._lock:
            self._flag = False

    @switchpoint
    def wait(self, timeout=None):
        """If the internal flag is set, return immediately. Otherwise block
        until the flag gets set by another fiber calling :meth:`set`."""
        # Optimization for the case the Event is already set.
        if self._flag:
            return True
        hub = get_hub()
        try:
            with switch_back(timeout, lock=self._lock) as switcher:
                with self._lock:
                    # Need to check the flag again, now under the lock.
                    if self._flag:
                        return True
                    # Allow other fibers to wake us up via callback in set().
                    # The callback goes to switcher.switch directly() instead of
                    # __call__(), because the latter would try to lock our lock
                    # which is already held when callbacks are run by set().
                    handle = add_callback(self, switcher.switch)
                # See note in Lock.acquire() why we can call to hub.switch()
                # outside the lock.
                hub.switch()
        except BaseException as e:
            with self._lock:
                remove_callback(self, handle)
            if e is switcher.timeout:
                return False
            raise
        return True

    # Support for wait()

    def add_done_callback(self, callback, *args):
        with self._lock:
            if self._flag:
                callback(*args)
                return
            return add_callback(self, callback, args)

    def remove_done_callback(self, handle):
        with self._lock:
            remove_callback(self, handle)


# Utility functions for a condition to work with both Locks and RLocks.

def is_locked(lock):
    """Return whether a lock is locked.

    Suppors :class:`Lock`, :class:`RLock`, :class:`threading.Lock` and
    :class:`threading.RLock` instances.
    """
    if hasattr(lock, 'locked'):
        return lock.locked()
    elif hasattr(lock, '_is_owned'):
        return lock._is_owned()
    else:
        raise TypeError('expecting Lock/RLock')

def acquire_restore(lock, state):
    """Acquire a lock and restore its state."""
    if hasattr(lock, '_acquire_restore'):
        lock._acquire_restore(state)
    elif hasattr(lock, 'acquire'):
        lock.acquire()
    else:
        raise TypeError('expecting Lock/RLock')

def release_save(lock):
    """Release a lock and return its state."""
    if hasattr(lock, '_release_save'):
        return lock._release_save()
    elif hasattr(lock, 'release'):
        lock.release()
    else:
        raise TypeError('expecting Lock/RLock')

def thread_lock(lock):
    """Return the thread lock for *lock*."""
    if hasattr(lock, '_lock'):
        return lock._lock
    elif hasattr(lock, 'acquire'):
        return lock
    else:
        raise TypeError('expecting Lock/RLock')


class Condition(object):
    """A condition.

    A condition is always associated with a lock. The state of the condition
    may only change when the caller has acquired the lock. While the lock is
    held, a condition can be waited for using :meth:`wait`. The wait method
    will release the lock just before blocking itself, so that another fiber
    can call :meth:`notify` to notify the condition.

    The difference between a condition and an :class:`Event` is that a
    condition is edge-trigerred. This means that when a condition is notified,
    only fibers that are waiting *at the time of notification* are unblocked.
    Any fiber that calls :meth:`wait` after the notification, will block until
    the next notification. This also explains why a lock is needed. Without the
    lock there would be a race condition between notification and waiting.
    """

    __slots__ = ('_lock', '_callbacks')

    def __init__(self, lock=None):
        """
        The *lock* argument can be used to share a lock between multiple
        conditions. It must be a :class:`Lock` or :class:`RLock` instance. If
        no lock is provided, a :class:`RLock` is allocated.
        """
        self._lock = lock or RLock()
        self._callbacks = None

    acquire = lambda self, *args: self._lock.acquire(*args)
    release = lambda self: self._lock.release()
    __enter__ = lambda self: self._lock.acquire()
    __exit__ = lambda self, *exc_info: self.release()

    def notify(self, n=1):
        """Raise the condition and wake up fibers waiting on it.

        The optional *n* parameter specifies how many fibers will be notified.
        By default, one fiber is notified.
        """
        if not is_locked(self._lock):
            raise RuntimeError('lock is not locked')
        notified = [0]  # Work around lack of "nonlocal" in py27
        def walker(switcher, predicate):
            if not switcher.active:
                return False  # not not keep switcher that timed out
            if predicate and not predicate():
                return True
            if n >= 0 and notified[0] >= n:
                return True
            switcher.switch()
            notified[0] += 1
            return False  # only notify once
        walk_callbacks(self, walker)

    def notify_all(self):
        """Raise the condition and wake up all fibers waiting on it."""
        self.notify(-1)

    @switchpoint
    def wait(self, timeout=None):
        """Wait for the condition to be notified.

        The return value is True, unless a timeout occurred in which case the
        return value is False.

        The lock must be held before calling this method. This method will
        release the lock just before blocking itself, and it will re-acquire it
        before returning.
        """
        return self.wait_for(None, timeout)

    @switchpoint
    def wait_for(self, predicate, timeout=None):
        """Like :meth:`wait` but additionally for *predicate* to be true.

        The *predicate* argument must be a callable that takes no arguments.
        Its result is interpreted as a boolean value.
        """
        if not is_locked(self._lock):
            raise RuntimeError('lock is not locked')
        hub = get_hub()
        try:
            with switch_back(timeout, lock=thread_lock(self._lock)) as switcher:
                handle = add_callback(self, switcher, predicate)
                # See the comment in Lock.acquire() why it is OK to release the
                # lock here before calling hub.switch().
                # Also if this is a reentrant lock make sure it is fully released.
                state = release_save(self._lock)
                hub.switch()
        except BaseException as e:
            with self._lock:
                remove_callback(self, handle)
            if e is switcher.timeout:
                return False
            raise
        finally:
            acquire_restore(self._lock, state)
        return True


class QueueEmpty(Exception):
    """Queue is empty."""

class QueueFull(Exception):
    """Queue is full."""


class Queue(object):
    """A synchronized FIFO queue. """

    __slots__ = ('_maxsize', '_unfinished_tasks', '_heap', '_size', '_counter',
                 '_lock', '_notempty', '_notfull', '_alldone')

    def __init__(self, maxsize=0):
        """
        The *maxsize* argument specifies the maximum queue size. If it is less
        than or equal to zero, the queue size is infinite.
        """
        self._maxsize = maxsize
        self._unfinished_tasks = 0
        # Use a list/heapq even for a FIFO instead of a deque() because of the
        # latter's high memory use (see comment in Lock). For most protocols
        # there will be one Queue per connection so a low memory footprint is
        # very important.
        self._heap = []
        self._size = 0
        self._counter = 0
        # Use a threading.Lock so that put_nowait() and get_nowait() don't need
        # to be a switchpoint. Also it is more efficient.
        self._lock = threading.Lock()
        self._notempty = Condition(self._lock)
        self._notfull = Condition(self._lock)
        self._alldone = Condition(self._lock)

    def _get_item_priority(self, item):
        # Priority function: FIFO queue by default
        self._counter += 1
        return self._counter

    def qsize(self):
        """Return the size of the queue, which is the sum of the size of all
        its elements."""
        return self._size

    empty = lambda self: self.qsize() == 0
    full = lambda self: self.qsize() >= self.maxsize > 0

    maxsize = property(lambda self: self._maxsize)
    unfinished_tasks = property(lambda self: self._unfinished_tasks)

    @switchpoint
    def put(self, item, block=True, timeout=None, size=None):
        """Put *item* into the queue.

        If the queue is currently full and *block* is True (the default), then
        wait up to *timeout* seconds for space to become available. If no
        timeout is specified, then wait indefinitely.

        If the queue is full and *block* is False or a timeout occurs, then
        raise a :class:`QueueFull` exception.

        The optional *size* argument may be used to specify a custom size for
        the item. The total :meth:`qsize` of the queue is the sum of the sizes
        of all the items. The default size for an item is 1.
        """
        if size is None:
            size = 1
        with self._lock:
            priority = self._get_item_priority(item)
            while self._size + size > self.maxsize > 0:
                if not block:
                    raise QueueFull
                if not self._notfull.wait_for(lambda: self._size+size <= self.maxsize, timeout):
                    raise QueueFull
            heapq.heappush(self._heap, (priority, size, item))
            self._size += size
            self._unfinished_tasks += 1
            self._notempty.notify()

    def put_nowait(self, item, size=None):
        """"Equivalent of ``put(item, False)``."""
        # Don't don't turn this method into a switchpoint as put() will never
        # switch if block is False. This can be done by calling the function
        # wrapped by the @switchpoint wrapper directly.
        return self.put.__wrapped__(self, item, False, size=size)

    @switchpoint
    def get(self, block=True, timeout=None):
        """Pop an item from the queue.

        If the queue is not empty, an item is returned immediately. Otherwise,
        if *block* is True (the default), wait up to *timeout* seconds for an
        item to become available. If not timeout is provided, then wait
        indefinitely.

        If the queue is empty and *block* is false or a timeout occurs, then
        raise a :class:`QueueEmpty` exception.
        """
        with self._lock:
            while not self._heap:
                if not block:
                    raise QueueEmpty
                if not self._notempty.wait(timeout):
                    raise QueueEmpty
            prio, size, item = heapq.heappop(self._heap)
            self._size -= size
            if 0 <= self._size < self.maxsize:
                self._notfull.notify()
        return item

    def get_nowait(self):
        """"Equivalent of ``get(False)``."""
        # See note in put_nowait()
        return self.get.__wrapped__(self, False)

    def task_done(self):
        """Mark a task as done."""
        with self._lock:
            unfinished = self._unfinished_tasks - 1
            if unfinished < 0:
                raise RuntimeError('task_done() called too many times')
            elif unfinished == 0:
                self._alldone.notify()
            self._unfinished_tasks = unfinished

    def join(self):
        """Wait until all tasks are done."""
        with self._lock:
            while self._unfinished_tasks > 0:
                self._alldone.wait()


class LifoQueue(Queue):
    """A queue with LIFO behavior.

    See :class:`Queue` for a description of the API.
    """

    __slots__ = Queue.__slots__

    def _get_item_priority(self, item):
        # Priority function for a LIFO queue
        self._counter += 1
        return -self._counter


class PriorityQueue(Queue):
    """A priority queue.

    Items that are added via :meth:`~Queue.put` are typically ``(priority,
    item)`` tuples. Lower values for priority indicate a higher priority.

    See :class:`Queue` for a description of the API.
    """

    __slots__ = Queue.__slots__

    def _get_item_priority(self, item):
        # Priority function for a priority queue: item should typically be a
        # (priority, item) tuple
        return item
