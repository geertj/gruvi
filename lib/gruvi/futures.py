#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import time
import threading
import pyuv

from . import fibers, compat, logging, util
from .hub import switchpoint, switch_back
from .sync import Event, Queue
from .errors import Timeout, Cancelled
from .callbacks import add_callback, remove_callback, run_callbacks

__all__ = ['Future', 'PoolBase', 'FiberPool', 'ThreadPool', 'get_io_pool',
           'get_cpu_pool', 'blocking', 'wait', 'as_completed']


class Future(object):
    """The state of an asynchronous function call.

    A future captures the state and the future result of an asynchronous
    function call. Futures are not instantiated directly but are created by a
    :class:`PoolBase` implementation. The pool accepts work in the form of a
    Python function via its :meth:`~PoolBase.submit` method. This method
    returns a future representing the state and the result of the function that
    will be executed asynchronously in the pool.

    A future progresses through different states during its lifecyle:

    * Initially the future is in the pending state.
    * Once the pool has capacity to run the function, it moves to the running
      state. In this state, :meth:`~Future.running` will return ``True``.
    * Once the function completes or raises an exception, the future moves to
      the done state. In this state, :meth:`~Future.done` will return ``True``.

    The future and the asynchronous function it represents are two distinct
    entities but for brevity the terms are often used interchangeably,
    including in this manual. For example, if the asynchronous function
    completes it is said that the future has completed, and cancelling the
    future really means cancelling the asynchronous function it is capturing
    the state of.
    """

    __slots__ = ('_result', '_state', '_lock', '_done', '_callbacks')

    S_PENDING, S_RUNNING, S_RUNNING_NOCANCEL, S_DONE, S_EXCEPTION = range(5)

    def __init__(self):
        self._result = None
        self._state = self.S_PENDING
        self._lock = threading.Lock()
        self._done = Event()
        self._callbacks = None

    def running(self):
        """Return whether this future is running. """
        return self._state in (self.S_RUNNING, self.S_RUNNING_NOCANCEL)

    def cancelled(self):
        """Return whether this future was successfully cancelled."""
        return self._state == self.S_EXCEPTION and isinstance(self._result, Cancelled)

    def done(self):
        """Return whether this future is done."""
        return self._state in (self.S_DONE, self.S_EXCEPTION)

    def cancel(self):
        """Cancel the execution of the async function, if possible.

        This method marks the future as done and sets the :class:`Cancelled`
        exception.

        A future that is not running can always be cancelled. However when a
        future is running, the ability to cancel it depends on the pool
        implementation. For example, a fiber pool can cancel running fibers but
        a thread pool cannot.

        Return ``True`` if the future could be cancelled, ``False`` otherwise.
        """
        # We leverage/abuse our _done Event's thread lock as our own lock.
        # Since it's a private copy it should be OK, and it saves some memory.
        # Just be sure that we don't modify the event with the lock held.
        with self._lock:
            if self._state not in (self.S_PENDING, self.S_RUNNING):
                return False
            self._result = Cancelled('cancelled by Future.cancel()')
            self._state = self.S_EXCEPTION
            self._done.set()
            return True

    @switchpoint
    def result(self, timeout=None):
        """Wait for the future to complete and return its result.

        If the function returned normally, its return value is returned here.
        If the function raised an exception, the exception is re-raised here.
        """
        if not self._done.wait(timeout):
            raise Timeout('timeout waiting for future')
        # No more state changes after _done is set so no lock needed.
        if self._state == self.S_EXCEPTION:
            raise compat.saved_exc(self._result)
        return self._result

    @switchpoint
    def exception(self, timeout=None):
        """Wait for the async function to complete and return its exception.

        If the function did not raise an exception this returns ``None``.
        """
        if not self._done.wait(timeout):
            raise Timeout('timeout waiting for future')
        if self._state == self.S_EXCEPTION:
            return self._result

    def add_done_callback(self, callback, *args):
        """Add a callback that gets called when the future completes.

        The callback will be called in the context of the fiber that sets the
        future's result. The callback is called with the positional arguments
        *args* provided to this method.

        The return value is an opaque handle that can be used with
        :meth:`~gruvi.Future.remove_done_callback` to remove the callback.

        If the future has already completed, then the callback is called
        immediately from this method and the return value will be ``None``.
        """
        with self._lock:
            if self._state not in (self.S_DONE, self.S_EXCEPTION):
                return add_callback(self, callback, args)
        callback(*args)

    def remove_done_callback(self, handle):
        """Remove a callback that was added by :meth:`~Future.add_done_callback`.

        It is not an error to remove a callback that was already removed.
        """
        with self._lock:
            remove_callback(self, handle)

    # The following are internal functions used by the pool implementations.

    def set_running(self, can_cancel=False):
        # Set the future in the running state.
        with self._lock:
            if self._state != self.S_PENDING:
                return
            self._state = self.S_RUNNING if can_cancel else self.S_RUNNING_NOCANCEL

    def set_result(self, result):
        # Mark the future as done and set its result. If the future has already
        # completed, then this does nothing.
        with self._lock:
            if self._state in (self.S_DONE, self.S_EXCEPTION):
                return
            self._result = result
            self._state = self.S_DONE
        self._done.set()
        run_callbacks(self)

    def set_exception(self, exception):
        # Mark the future as done and set an exception. If the future has
        # already completed, then this does nothing.
        with self._lock:
            if self._state in (self.S_DONE, self.S_EXCEPTION):
                return
            self._result = exception
            self._state = self.S_EXCEPTION
        self._done.set()
        run_callbacks(self)


class PoolBase(object):
    """Base class for pools.

    A pool contains a set of workers that can execute function calls
    asynchronously.
    """

    _PoolClosing = object()

    def __init__(self, maxsize=None, minsize=0, name=None):
        """
        The *maxsize* argument specifies the maximum numbers of workers that
        will be created in the pool. If *maxsize* is ``None`` then the pool can
        grow without bound.

        Normally the pool starts with zero workers and grows up to *maxsize* on
        demand. The *minsize* parameter can be used to change this behavior an
        make sure that there will always be at least this many workers in the
        pool.

        The *name* parameter gives a name for this pool. The pool name will
        show up in log messages related to the pool.
        """
        self._maxsize = maxsize
        self._name = name or util.objref(self)
        self._minsize = minsize
        self._log = logging.get_logger()
        self._workers = set()
        # We never switch while holding the lock which means we can use a
        # threading lock which is more efficient than a fiber lock.
        self._lock = threading.Lock()
        self._queue = Queue()
        self._closing = False
        self._closed = Event()
        self._next_worker = 0
        for i in range(self._minsize):
            self._spawn_worker()
        if self._minsize:
            self._log.debug('pre-spawned {} workers', self._minsize)

    @property
    def maxsize(self):
        """The maximum size of this pool."""
        return self._maxsize

    @property
    def minsize(self):
        """The minimum size of this pool."""
        return self._minsize

    @property
    def name(self):
        """The pool name."""
        return self._name

    def _current_worker(self):
        raise NotImplementedError

    def _create_worker(self):
        raise NotImplementedError

    def _start_work(self, fut):
        raise NotImplementedError

    def _worker_main(self):
        # Main function for each worker in the pool.
        try:
            while True:
                work = None or self._queue.get()
                try:
                    if work is self._PoolClosing:
                        self._log.debug('worker shutting down')
                        break
                    func, args, fut = work
                    if fut.cancelled():
                        continue  # Future was cancelled before it could be run.
                    self._start_work(fut)
                    try:
                        result = func(*args)
                        fut.set_result(result)
                    except Cancelled as e:
                        self._log.debug('worker was cancelled ({!s})', e)
                        # The future might have cancelled itself so make sure
                        # to set the exception, possibly unnecessarily.
                        fut.set_exception(e)
                    except:
                        # OK to catch all since we will exit.
                        self._log.debug('uncaught exception in worker', exc_info=True)
                        fut.set_exception(sys.exc_info()[1])
                        break
                finally:
                    self._queue.task_done()
        finally:
            with self._lock:
                self._workers.remove(self._current_worker())
                if work is self._PoolClosing and self._workers:
                    self._queue.put_nowait(work)
                elif work is self._PoolClosing:
                    self._closed.set()
                else:
                    self._spawn_workers()

    def _spawn_worker(self):
        # Spawn a single new worker. The lock must be held.
        name = '{}:{}'.format(self._name, self._next_worker)
        self._next_worker += 1
        self._workers.add(self._create_worker(name))

    def _spawn_workers(self):
        # Spawn new workers if required. The lock must be held.
        # Note that holding the lock prevents work from being added to the
        # queue but not from being drained. The result is that the value of
        # 'tospawn' we calculate below may be too high. However, since we limit
        # the number of workers we spin up in one batch, this is not a big deal
        # and actually simplifies the overall locking significantly (we cannot
        # do a _queue._get() under a plain lock as it might block the thread).
        nworkers = len(self._workers)
        queued = self._queue.qsize()
        active_workers = self._queue.unfinished_tasks - queued
        idle_workers = nworkers - active_workers
        wanted = max(0, queued - idle_workers, self._minsize - nworkers)
        mayspawn = max(0, self._maxsize or wanted - nworkers)
        tospawn = min(10, wanted, mayspawn)
        for i in range(tospawn):
            self._spawn_worker()
        if tospawn:
            self._log.debug('spawned {} workers, total = {}', tospawn, len(self._workers))

    def submit(self, func, *args):
        """Run *func* asynchronously.

        The function is run in the pool which will run it asynchrously. The
        function is called with positional argument *args*.

        The return value is a :class:`Future` that captures the state and the
        future result of the asynchronous function call.
        """
        with self._lock:
            if self._closing:
                raise RuntimeError('pool is closing/closed')
            result = Future()
            self._queue.put_nowait((func, args, result))
            self._spawn_workers()
        return result

    @switchpoint
    def map(self, func, *iterables, **kwargs):
        """Apply *func* to the elements of the sequences in *iterables*.

        All invocations of *func* are run in the pool. If multiple iterables
        are provided, then *func* must take this many arguments, and is applied
        with one element from each iterable. All iterables must yield the same
        number of elements.

        An optional *timeout* keyword argument may be provided to specify a
        timeout.

        This returns a generator yielding the results.
        """
        with self._lock:
            if self._closing:
                raise RuntimeError('pool is closing/closed')
            timeout = kwargs.pop('timeout', None)
            futures = []
            for args in zip(*iterables):
                result = Future()
                self._queue.put_nowait((func, args, result))
                futures.append(result)
            self._spawn_workers()
        try:
            with switch_back(timeout):
                for future in futures:
                    yield future.result()
        except Exception:
            # Timeout, GeneratorExit or future.set_exception()
            for future in futures:
                if not future.done():
                    future.cancel()
            raise

    @switchpoint
    def join(self):
        """Wait until all jobs in the pool have completed.

        New submissions are not blocked. This means that if you continue adding
        work via :meth:`~PoolBase.submit` or :meth:`~PoolBase.map` then this
        method might never finish.
        """
        self._queue.join()

    @switchpoint
    def close(self):
        """Close the pool and wait for all workers to exit.

        New submissions will be blocked. Workers will exit once their current
        job is finished. This method will return after all workers have exited.
        """
        with self._lock:
            if self._closing:
                return
            self._closing = True
            if not self._workers:
                self._closed.set()
                return
            self._queue.put_nowait(self._PoolClosing)
        self._closed.wait()


class FiberPool(PoolBase):
    """A pool that uses fiber workers."""

    def __init__(self, *args, **kwargs):
        # Provided in order not to repeat the PoolBase.__init__ doc string.
        super(FiberPool, self).__init__(*args, **kwargs)

    def _current_worker(self):
        return fibers.current_fiber()

    def _create_worker(self, name):
        fiber = fibers.Fiber(self._worker_main, name=name)
        fiber.start()
        return fiber

    def _cancel_fiber(self, fut, fiber):
        if fut.cancelled():
            fiber.cancel()

    def _start_work(self, fut):
        fut.set_running(True)
        fut.add_done_callback(self._cancel_fiber, fut, self._current_worker())


Pool = FiberPool


class ThreadPool(PoolBase):
    """A pool that uses thread workers."""

    def __init__(self, *args, **kwargs):
        # Provided in order not to repeat the PoolBase.__init__ doc string.
        super(ThreadPool, self).__init__(*args, **kwargs)

    def _current_worker(self):
        return threading.current_thread()

    def _create_worker(self, name):
        thread = threading.Thread(target=self._worker_main, name=name)
        # Mark the threads in the pool as daemonic. This allows the program to
        # exit if the user did not close() the pool. This is useful especially
        # because there's implicitly created pools (the IO and thread pool) and
        # we cannot expect the user to close those.
        thread.daemon = True
        thread.start()
        return thread

    def _start_work(self, fut):
        fut.set_running(False)


# When constructing a pool it doesn't start any workers until they are needed.
# This makes it OK to instantiate the pools ahead of time.

_io_pool = ThreadPool(20, name='Io')
_cpu_pool = ThreadPool(len(pyuv.util.cpu_info()), name='Cpu')

def get_io_pool():
    """Return the thread pool for IO tasks.

    By default there is one IO thread pool per application, which is shared
    with all threads.
    """
    return _io_pool

def get_cpu_pool():
    """Return the thread pool for CPU intenstive tasks.

    By default there is one CPU thread pool per application, which it is shared
    with all threads.
    """
    return _cpu_pool


def blocking(func, *args, **kwargs):
    """Run a function that uses blocking IO.

    The function is run in the IO thread pool.
    """
    pool = get_io_pool()
    fut = pool.submit(func, *args, **kwargs)
    return fut.result()


@switchpoint
def _wait(pending, timeout):
    # An iterator/generator that waits for objects in the list *pending*,
    # yielding them as they become ready. The pending list is mutated.
    done = []
    have_items = Event()
    def callback(i):
        done.append(pending[i])
        pending[i] = None
        have_items.set()
    handles = [pending[i].add_done_callback(callback, i) for i in range(len(pending))]
    if timeout is not None:
        end_time = time.time() + timeout
    try:
        while pending:
            if timeout is not None:
                timeout = max(0, end_time - time.time())
            if not have_items.wait(timeout):
                raise Timeout('timeout waiting for objects')
            i = 0
            while i < len(done):
                yield done[i]
                i += 1
            del done[:]
            have_items.clear()
    finally:
        for i in range(len(pending)):
            if pending[i] is not None:
                pending[i].remove_done_callback(handles[i])


@switchpoint
def as_completed(objects, count=None, timeout=None):
    """Wait for one or more waitable objects, yielding them as they become
    ready.

    This is the iterator/generator version of :func:`wait`.
    """
    for obj in objects:
        if not hasattr(obj, 'add_done_callback'):
            raise TypeError('Expecting sequence of waitable objects')
    if count is None:
        count = len(objects)
    if count < 0 or count > len(objects):
        raise ValueError('count must be between 0 and len(objects)')
    if count == 0:
        return
    pending = list(objects)
    for obj in _wait(pending, timeout):
        yield obj
        count -= 1
        if count == 0:
            break


@switchpoint
def wait(objects, count=None, timeout=None):
    """Wait for one or more waitable objects.

    This method waits until *count* elements from the sequence of waitable
    objects *objects* have become ready. If *count* is ``None`` (the default),
    then wait for all objects to become ready.

    What "ready" is means depends on the object type. A waitable object is a
    objects that implements the ``add_done_callback()`` and
    ``remove_done_callback`` methods. This currently includes:

      * :class:`~gruvi.Event` - an event is ready when its internal flag is set.
      * :class:`~gruvi.Future` - a future is ready when its result is set.
      * :class:`~gruvi.Fiber` - a fiber is ready when has terminated.
      * :class:`~gruvi.Process` - a process is ready when the child has exited.
    """
    for obj in objects:
        if not hasattr(obj, 'add_done_callback'):
            raise TypeError('Expecting sequence of waitable objects')
    if count is None:
        count = len(objects)
    if count < 0 or count > len(objects):
        raise ValueError('count must be between 0 and len(objects)')
    if count == 0:
        return [], objects
    pending = list(objects)
    done = []
    try:
        for obj in _wait(pending, timeout):
            done.append(obj)
            if len(done) == count:
                break
    except Timeout:
        pass
    return done, list(filter(bool, pending))
