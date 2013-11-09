# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import pyuv
import time
import threading

import pyuv
from . import sync, fibers
from .hub import switchpoint

__all__ = ['Future', 'Pool', 'FiberPool', 'ThreadPool', 'get_io_pool',
           'get_cpu_pool', 'blocking']


class Future(object):
    """The result of an asynchronous function call.

    Futures are created by :class:`FiberPool.submit` and :class:`ThreadPool.submit`
    and represent the not-yet-available result of the submitted functions.

    This class is loosely modeled after :class:`concurrent.futures.Future` and
    :class:`asyncio.Future`, but with an API that uses Gruvi signals.
    """

    def __init__(self):
        self._value = None
        self._exception = None
        self._completed = False
        self._done = sync.Signal()

    @property
    def value(self):
        """The result of the async function, if available."""
        return self._value

    @property
    def exception(self):
        """The exception that was raised by the async function, if available."""
        return self._exception

    @property
    def completed(self):
        """Whether the async function has already completed."""
        return self._completed

    @property
    def done(self):
        """A signal that is raised when the future is done.

        You can call ``wait()`` on this signal, or ``connect()`` to it.

        Callback arguments: ``callback(value, exception)``.
        """
        return self._done

    def result(self, timeout=None):
        """Wait for the asynchronous function to complete, and return its
        result.

        If the function returned a value, it is returned here. If an exception
        was raised instead, it is re-raised here.
        """
        if not self._completed:
            self.done.wait(timeout)
        if self._exception:
            raise self._exception
        return self._value

    def set_result(self, value=None, exception=None):
        """Set the result of the future."""
        self._value = value
        self._exception = exception
        self._completed = True
        self.done.emit(value, exception)


class PoolBase(object):
    """Base class for the thread and fiber pools."""

    _StopWorker = object()

    def __init__(self, maxsize=4):
        self.maxsize = maxsize
        self._workers = set()
        self._queue = sync.Queue()
        self._active = 0
        self._closed = False

    def _current_worker(self):
        raise NotImplemented

    def _spawn_worker(self):
        raise NotImplemented

    def _worker_main(self):
        # Main function for each worker in the pool.
        while True:
            with self._queue.lock:
                if self.maxsize is not None and len(self._workers) > self.maxsize:
                    break  # Die voluntarily
                work = self._queue.get()
                if work is self._StopWorker:
                    break
                func, args, fut = work
                self._active += 1
            res = exc = None
            try:
                res = func(*args)
            except Exception as e:
                exc = e
            fut.set_result(res, exc)
            with self._queue.lock:
                self._active -= 1
        self._workers.remove(self._current_worker())

    def _spawn_workers(self):
        # Spawn new threads if required.
        with self._queue.lock:
            if self.maxsize is None:
                idle = len(self._workers) - self._active
                tospawn = len(self._queue) - idle
            else:
                available = max(0, self.maxsize - len(self._workers))
                idle = len(self._workers) - self._active
                wanted = max(0, len(self._queue) - idle)
                tospawn = min(available, wanted)
            for i in range(tospawn):
                worker = self._spawn_worker()
                self._workers.add(worker)

    @property
    def closed(self):
        """Return whether the pool has been closed."""
        return self._closed

    @property
    def size(self):
        """Return the current size of the pool."""
        return len(self._workers)

    def submit(self, func, *args, **kwargs):
        """Submit function *func* to the pool, which will run it asynchronously.
        
        The function is called with positional argument *args*.
        """
        if self._closed:
            raise RuntimeError('ThreadPool is closed')
        result = Future()
        with self._queue.lock:
            self._queue.put((func, args, result))
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
            raise RuntimeError('ThreadPool is closed')
        timeout = kwargs.pop('timeout', None)
        futures = [self.submit(func, *args) for args in zip(*iterables)]
        for future in futures:
            yield future.result()

    @switchpoint
    def close(self):
        """Close down the threadpool for new submissions, and then wait until
        all work is completed."""
        if self._closed:
            return
        self._closed = True
        with self._queue.lock:
            for i in range(len(self._workers)):
                self._queue.put(self._StopWorker)
            if len(self._queue) > 0:
                self._queue.size_changed.wait(waitfor=(lambda o,n: n == 0))
        assert len(self._queue) == 0


class FiberPool(PoolBase):
    """Execute functions asynchronously in a pool of fibers."""

    def __init__(self, maxsize=None):
        """Spawn up to *maxsize* fibers in the fiber pool. If maxsize is not
        provided, then there is no limit to the size of the pool.
        """
        super(Pool, self).__init__(maxsize)

    def _current_worker(self):
        return fibers.current_fiber()

    def _spawn_worker(self):
        worker = fibers.Fiber(self._worker_main)
        worker.start()
        return worker

Pool = FiberPool


class ThreadPool(PoolBase):
    """Execute functions asynchronously in a pool of threads."""

    _lock = threading.Lock()
    _io_pool = None
    _cpu_pool = None

    def __init__(self, maxsize=None):
        """Spawn up to *maxsize* threads in the thread pool. If maxsize is not
        provided, then it will be set to the number of cores in the system."""
        if maxsize is None:
            maxsize = len(pyuv.util.cpu_info())
        super(ThreadPool, self).__init__(maxsize)

    def _current_worker(self):
        return threading.current_thread()

    def _spawn_worker(self):
        worker = threading.Thread(target=self._worker_main)
        worker.start()
        return worker

    @classmethod
    def get_io_pool(cls):
        """Return the IO thread pool."""
        if cls._io_pool is None:
            with cls._lock:
                if cls._io_pool is None:
                    cls._io_pool = ThreadPool(20)
        return cls._io_pool

    @classmethod
    def get_cpu_pool(cls):
        """Return the CPU thread pool."""
        if cls._cpu_pool is None:
            with cls._lock:
                if cls._cpu_pool is None:
                    ncores = len(pyuv.util.cpu_info())
                    cls._cpu_pool = ThreadPool(ncores)
        return cls._cpu_pool


def get_io_pool():
    """Return the thread pool for IO tasks.

    By default there is one IO thread pool that is shared with all threads.
    This method is equivalent to :meth:`ThreadPool.get_io_pool`.
    """
    return ThreadPool.get_io_pool()

def get_cpu_pool():
    """Return the thread pool for CPU intenstive tasks.
    
    By default there is one CPU thread pool that is shared with all threads.
    This method is equivalent to :meth:`ThreadPool.get_cpu_pool`.
    """
    return ThreadPool.get_cpu_pool()


def blocking(func, *args, **kwargs):
    """Run a function that uses blocking IO.

    The function is run in the IO thread pool. 
    """
    pool = get_io_pool()
    fut = pool.submit(func, *args, **kwargs)
    return fut.result()
