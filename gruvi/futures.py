# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
import threading

from . import fibers, compat
from .hub import switchpoint, switch_back
from .sync import Event, Queue

__all__ = ['Future', 'PoolBase', 'FiberPool', 'ThreadPool', 'get_io_pool',
           'get_cpu_pool', 'blocking']


class Future(object):
    """The result of an asynchronous function call."""

    __slots__ = ['_result', '_exception', '_done']

    def __init__(self):
        self._result = None
        self._exception = None
        self._done = Event()

    def done(self):
        """Return whether this future is done."""
        return bool(self._done)

    def result(self):
        """The result of the async function, if available."""
        self._done.wait()
        if self._exception:
            raise compat.saved_exc(self._exception)
        return self._result

    def exception(self):
        """The exception that was raised by the async function, if available."""
        self._done.wait()
        return self._exception

    def set_result(self, result):
        """Mark the future as done and set its result."""
        self._result = result
        self._done.set()

    def set_exception(self, exception):
        """Mark the future as done and set an exception."""
        self._exception = exception
        self._done.set()


class PoolBase(object):
    """Base class for the thread and fiber pools."""

    _StopWorker = object()

    def __init__(self, maxsize=None, single_shot=False, name=None):
        self.maxsize = maxsize
        self.single_shot = single_shot
        self.name = name
        self._workers = set()
        self._queue = Queue()
        self._closed = False
        # The lock is short lived so no need for a fiber aware lock.
        self._lock = threading.Lock()

    def _current_worker(self):
        raise NotImplemented

    def _spawn_worker(self):
        raise NotImplemented

    def _worker_main(self):
        # Main function for each worker in the pool.
        while True:
            work = self._queue.get()
            try:
                if work is self._StopWorker:
                    break
                func, args, fut = work
                try:
                    res = func(*args)
                except Exception as e:
                    fut.set_exception(e)
                else:
                    fut.set_result(res)
            finally:
                self._queue.task_done()
            if self.single_shot:
                break
        self._workers.remove(self._current_worker())

    def _spawn_workers(self):
        # Spawn new workers if required.
        with self._lock:
            active = self._queue.unfinished_tasks
            idle = max(0, len(self._workers) - active)
            if self.maxsize is None:
                tospawn = self._queue.qsize() - idle
            else:
                available = max(0, self.maxsize - len(self._workers))
                wanted = max(0, self._queue.qsize() - idle)
                tospawn = min(available, wanted)
            for i in range(tospawn):
                self._spawn_worker()

    def submit(self, func, *args):
        """Submit function *func* to the pool, which will run it asynchronously.

        The function is called with positional argument *args*.
        """
        if self._closed:
            raise RuntimeError('pool is closed')
        result = Future()
        self._queue.put_nowait((func, args, result))
        self._spawn_workers()
        return result

    @switchpoint
    def map(self, func, *iterables, **kwargs):
        """Apply *func* to the elements of the sequences in *iterables*.

        If multiple iterables are provided, then *func* must take this many
        arguments, and is applied with one element from each iterable. All
        iterables must yield the same number of elements.

        An optional *timeout* keyword argument may be provided to specify a
        timeout.

        This returns a generator yielding the results.
        """
        if self._closed:
            raise RuntimeError('pool is closed')
        timeout = kwargs.pop('timeout', None)
        # XXX: futures should be cancelled on timeout.
        with switch_back(timeout):
            futures = [self.submit(func, *args) for args in zip(*iterables)]
            for future in futures:
                yield future.result()

    @switchpoint
    def join(self):
        """Wait until all jobs in the pool have completed."""
        self._queue.join()

    @switchpoint
    def close(self):
        """Close the pool.

        New submissions will be blocked. Once all current jobs have finished,
        the workers will be stopped, and this method will return.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for i in range(len(self._workers)):
                self._queue.put(self._StopWorker)
        self._queue.join()


class FiberPool(PoolBase):
    """Execute functions asynchronously in a pool of fibers."""

    def _current_worker(self):
        return fibers.current_fiber()

    def _spawn_worker(self):
        name = '{0}-{1}'.format(self.name, len(self._workers)) if self.name else None
        fiber = fibers.Fiber(self._worker_main, name=name)
        fiber.start()
        self._workers.add(fiber)

Pool = FiberPool


class ThreadPool(PoolBase):
    """Execute functions asynchronously in a pool of threads."""

    def _current_worker(self):
        return threading.current_thread()

    def _spawn_worker(self):
        name = '{0}-{1}'.format(self.name, len(self._workers)) if self.name else None
        thread = threading.Thread(target=self._worker_main, name=name)
        # Don't block program exit if the user forgot to close() the pool,
        # especially because there's implicitly created pools.
        thread.daemon = True
        thread.start()
        self._workers.add(thread)


# When constructing a pool it doesn't start any workers until they are needed.
# This makes it OK to instantiate the pools ahead of time.

_io_pool = ThreadPool(20, name='Io')
_cpu_pool = ThreadPool(len(pyuv.util.cpu_info()), name='Cpu')

def get_io_pool():
    """Return the thread pool for IO tasks.

    By default there is one IO thread pool that is shared with all threads.
    """
    return _io_pool

def get_cpu_pool():
    """Return the thread pool for CPU intenstive tasks.

    By default there is one CPU thread pool that is shared with all threads.
    """
    return _cpu_pool


def blocking(func, *args, **kwargs):
    """Run a function that uses blocking IO.

    The function is run in the IO thread pool.
    """
    pool = get_io_pool()
    fut = pool.submit(func, *args, **kwargs)
    return fut.result()
