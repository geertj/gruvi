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

from .hub import switchpoint, get_hub, switch_back
from .errors import Timeout

__all__ = ['Lock', 'RLock', 'Event', 'Condition', 'QueueEmpty', 'QueueFull',
           'Queue', 'LifoQueue', 'PriorityQueue']


# All primitives in this module a thread safe!


class _Lock(object):
    """Base class for regular and reentrant locks."""

    __slots__ = ('_reentrant', '_lock', '_locked', '_owner', '_waiters')

    def __init__(self, reentrant):
        # Allocate a new lock
        self._reentrant = reentrant
        self._lock = threading.Lock()
        self._locked = 0
        self._owner = None
        # The _waiters attribute is initialized with a list on first use. We
        # use a list instead of a deque to save on memory, even if a list has
        # worse asymptotic performance. A lock is a very fundamental data
        # structure that should be fast and small. On my 64-bit system, an
        # empty deque is 624 bytes vs just 72 for a list.
        self._waiters = None

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
            with switch_back(timeout) as switcher:
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
                    if self._waiters is None:
                        self._waiters = []
                    self._waiters.append(switcher)
                # It is safe to call hub.switch() outside the lock. Another
                # thread could have called acquire()+release(), thereby firing
                # the switchback. However the switchback only schedules the
                # switchback in our hub, it won't execute it yet. So the
                # switchback won't actually happen until we switch to the hub.
                hub.switch()
                # Here the lock should be ours
                assert self._owner is fibers.current()
        except Exception as e:
            # Likely a Timeout but could also be e.g. Cancelled
            with self._lock:
                # Search for switcher from the end which is where we're more
                # likely to find it.
                for i in reversed(range(len(self._waiters))):
                    if self._waiters[i] is switcher:
                        del self._waiters[i]
                        break
            if isinstance(e, Timeout):
                return False
            raise
        return True

    def release(self):
        """Release the lock."""
        with self._lock:
            if not self._locked:
                raise RuntimeError('lock not currently held')
            elif self._reentrant and self._owner is not fibers.current():
                raise RuntimeError('lock not owned by this fiber')
            if self._locked > 1:
                self._locked -= 1
            elif not self._waiters:
                self._locked = 0
                self._owner = None
            else:
                # Don't unlock + lock but rather pass the lock directly to the
                # fiber that is next in line.
                switcher = self._waiters.pop(0)
                self._owner = switcher.fiber
                switcher()

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

    __slots__ = ('_flag', '_lock', '_waiters')

    def __init__(self):
        self._flag = False
        self._lock = threading.Lock()
        self._waiters = None

    def __nonzero__(self):
        return self._flag

    __bool__ = __nonzero__
    is_set = __nonzero__

    def set(self):
        """Set the internal flag, and wake up any fibers blocked on :meth:`wait`."""
        with self._lock:
            if self._flag:
                return
            self._flag = True
            if not self._waiters:
                return
            for notify in self._waiters:
                notify()
            del self._waiters[:]

    def clear(self):
        """Clear the internal flag."""
        with self._lock:
            self._flag = False

    @switchpoint
    def wait(self, timeout=None):
        """If the internal flag is set, return immediately. Otherwise block
        until the flag gets set by another fiber calling :meth:`set`."""
        hub = get_hub()
        self._lock.acquire()
        try:
            if self._flag:
                return
            with switch_back(timeout) as switcher:
                if self._waiters is None:
                    self._waiters = []
                self._waiters.append(switcher)
                self._lock.release()
                try:
                    hub.switch()
                finally:
                    self._lock.acquire()
        except Exception:
            for i in reversed(range(len(self._waiters))):
                if self._waiters[i] is switcher:
                    del self._waiters[i]
                    break
            raise
        finally:
            self._lock.release()


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

    __slots__ = ('_lock', '_waiters')

    def __init__(self, lock=None):
        """
        The *lock* argument can be used to share a lock between multiple
        conditions. It must be a :class:`Lock` or :class:`RLock` instance. If
        no lock is provided, a :class:`RLock` is allocated.
        """
        self._lock = lock or RLock()
        self._waiters = []

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
        if not self._waiters:
            return
        notified = 0
        for i in range(min(n, len(self._waiters))):
            notify, predicate = self._waiters[i-notified]
            if callable(predicate) and not predicate():
                continue
            notify()
            del self._waiters[i-notified]
            notified += 1

    def notify_all(self):
        """Raise the condition and wake up all fibers waiting on it."""
        self.notify(len(self._waiters))

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
        hub = get_hub()
        if not is_locked(self._lock):
            raise RuntimeError('lock is not locked')
        try:
            with switch_back(timeout) as switcher:
                self._waiters.append((switcher, predicate))
                # See the comment in Lock.acquire() why it is OK to release the
                # lock here before calling hub.switch().
                # Also if this is a reentrant lock make sure it is fully released.
                state = release_save(self._lock)
                hub.switch()
        except Exception as e:
            for i in reversed(range(len(self._waiters))):
                if self._waiters[i][0] is switcher:
                    del self._waiters[i]
                    break
            if isinstance(e, Timeout):
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
        return self.put.func(self, item, False, size=size)

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
        return self.get.func(self, False)

    def clear(self):
        """Remove all elements from the queue."""
        with self._lock:
            del self._heap[:]
            self._notfull.notify()

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
