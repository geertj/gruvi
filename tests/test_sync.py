#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function, division

import random
import threading

import gruvi
from gruvi.hub import get_hub
from support import UnitTest, unittest


def lock_unlock(lock, count=50):
    failed = 0
    for i in range(count):
        # the granularity of libuv's timers is 1ms. the statement below
        # therefore sleeps 0ms 75% of the time, and 1ms 25% of the time.
        gruvi.sleep(random.randint(0, 10)/10000)
        lock.acquire()
        gruvi.sleep(random.randint(0, 10)/10000)
        failed += (1 if lock._locked != 1 else 0)
        lock.release()
    return failed


class TestLock(UnitTest):

    def test_basic(self):
        # Ensure that acquire() and release() works.
        lock = gruvi.Lock()
        self.assertFalse(lock.locked())
        lock.acquire()
        self.assertTrue(lock.locked())
        lock.release()
        self.assertFalse(lock.locked())

    def test_timeout(self):
        # Ensure that the timeout argument to acquire() works.
        hub = get_hub()
        lock = gruvi.Lock()
        lock.acquire()
        t0 = hub.loop.now()
        self.assertFalse(lock.acquire(timeout=0.01))
        t1 = hub.loop.now()
        self.assertGreater(t1-t0, 10)
        self.assertFalse(lock._waiters)

    def test_non_blocking(self):
        # Ensure that the blocking argument to acquire() works.
        lock = gruvi.Lock()
        lock.acquire()
        self.assertFalse(lock.acquire(blocking=False))
        self.assertFalse(lock._waiters)

    def test_context_manager(self):
        # Ensure that a lock can be used as a context manager.
        lock = gruvi.Lock()
        with lock:
            self.assertTrue(lock.locked())
        self.assertFalse(lock.locked())

    def test_acquire_release_threads(self):
        # Ensure that a lock can be locked and unlocked in different threads.
        lock = gruvi.Lock()
        sync = gruvi.Lock()
        failed = [0]
        def thread_lock():
            lock.acquire()
            failed[0] += (1 if not lock.locked() else 0)
            sync.release()
        def thread_unlock():
            sync.acquire()
            lock.release()
            failed[0] += (1 if lock.locked() else 0)
            sync.release()
        sync.acquire()
        t1 = threading.Thread(target=thread_lock)
        t2 = threading.Thread(target=thread_unlock)
        t1.start(); t2.start()
        t1.join(); t2.join()
        self.assertEqual(failed[0], 0)

    def test_fiber_safety(self):
        # Start a bunch of fibers, each locking the rlock a few times before
        # unlocking it again. Ensure that the locks don't overlap.
        lock = gruvi.Lock()
        failed = [0]
        def run_test():
            failed[0] += lock_unlock(lock, 20)
        fibers = []
        for i in range(20):
            fiber = gruvi.Fiber(run_test)
            fiber.start()
            fibers.append(fiber)
        for fib in fibers:
            fib.join()
        self.assertEqual(failed[0], 0)

    def test_thread_safety(self):
        # Start a bunch of threads, each starting a bunch of fibers. Each fiber
        # will lock the rlock a few times before unlocking it again. Ensure
        # that the locks don't overlap.
        lock = gruvi.Lock()
        failed = [0]
        def run_test():
            failed[0] += lock_unlock(lock, 10)
        def run_thread():
            fibers = []
            for i in range(10):
                fiber = gruvi.Fiber(run_test)
                fiber.start()
                fibers.append(fiber)
            for fib in fibers:
                fib.join()
        threads = []
        for i in range(5):
            thread = threading.Thread(target=run_thread)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        self.assertEqual(failed[0], 0)


def lock_unlock_reentrant(lock, count=10):
    failed = 0
    for i in range(count):
        gruvi.sleep(random.randint(0, 10)/10000)
        lock.acquire()
        gruvi.sleep(random.randint(0, 10)/10000)
        failed += (1 if lock._locked != 1 else 0)
        lock.acquire()
        gruvi.sleep(random.randint(0, 10)/10000)
        failed += (1 if lock._locked != 2 else 0)
        lock.release()
        gruvi.sleep(random.randint(0, 10)/10000)
        failed += (1 if lock._locked != 1 else 0)
        lock.release()
    return failed


class TestRLock(UnitTest):

    def test_basic(self):
        # Lock and unlock the rlock once.
        lock = gruvi.RLock()
        lock.acquire()
        self.assertTrue(lock.locked())
        lock.release()
        self.assertFalse(lock.locked())

    def test_multiple(self):
        # Lock and unlock the rlock a few times
        lock = gruvi.RLock()
        for i in range(5):
            lock.acquire()
            self.assertEqual(lock._locked, i+1)
        self.assertTrue(lock.locked())
        for i in range(5):
            lock.release()
            self.assertEqual(lock._locked, 4-i)
        self.assertFalse(lock.locked())

    def test_timeout(self):
        # Ensure that the timeout argument to acquire() works.
        hub = get_hub()
        lock = gruvi.RLock()
        sync = gruvi.Lock()
        def lock_rlock():
            lock.acquire()
            sync.acquire()
            lock.release()
        # This needs a new fiber, as the same fiber *can* lock the same RLock twice.
        sync.acquire()
        fiber = gruvi.spawn(lock_rlock)
        gruvi.sleep(0)
        self.assertTrue(lock.locked())
        t0 = hub.loop.now()
        self.assertFalse(lock.acquire(timeout=0.01))
        t1 = hub.loop.now()
        # Internally the event loop uses timestamps with a 1ms granularity. So
        # allow for that.
        self.assertGreaterEqual(t1-t0, 10)
        sync.release()
        fiber.join()
        self.assertFalse(lock._waiters)

    def test_non_blocking(self):
        # Ensure that the blocking argument to acquire() works.
        lock = gruvi.RLock()
        sync = gruvi.Lock()
        def lock_rlock():
            lock.acquire()
            sync.acquire()
            lock.release()
        # This needs a new fiber, as the same fiber *can* lock the same RLock twice.
        sync.acquire()
        fiber = gruvi.spawn(lock_rlock)
        gruvi.sleep(0)
        self.assertTrue(lock.locked())
        self.assertFalse(lock.acquire(blocking=False))
        sync.release()
        fiber.join()
        self.assertFalse(lock._waiters)

    def test_context_manager(self):
        # Ensure that an RLock can be used as a context manager.
        lock = gruvi.RLock()
        with lock:
            self.assertTrue(lock.locked())
        self.assertFalse(lock.locked())

    def test_fiber_safety(self):
        # Start a bunch of fibers, each locking the rlock a few times before
        # unlocking it again. Ensure that the locks don't overlap.
        lock = gruvi.RLock()
        failed = [0]
        def run_test():
            failed[0] += lock_unlock_reentrant(lock, 10)
        fibers = []
        for i in range(20):
            fiber = gruvi.Fiber(run_test)
            fiber.start()
            fibers.append(fiber)
        for fib in fibers:
            fib.join()
        self.assertEqual(failed[0], 0)

    def test_thread_safety(self):
        # Start a bunch of threads, each starting a bunch of fibers. Each fiber
        # will lock the rlock a few times before unlocking it again. Ensure
        # that the locks don't overlap.
        lock = gruvi.RLock()
        failed = [0]
        def run_test():
            failed[0] += lock_unlock_reentrant(lock, 10)
        def run_thread():
            fibers = []
            for i in range(5):
                fiber = gruvi.Fiber(run_test)
                fiber.start()
                fibers.append(fiber)
            for fib in fibers:
                fib.join()
        threads = []
        for i in range(5):
            thread = threading.Thread(target=run_thread)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        self.assertEqual(failed[0], 0)


class TestEvent(UnitTest):

    def test_basic(self):
        # Ensure that an event can be set and cleared
        event = gruvi.Event()
        self.assertFalse(event)
        self.assertFalse(event._flag)
        event.set()
        self.assertTrue(event)
        self.assertTrue(event._flag)
        event.clear()
        self.assertFalse(event)
        self.assertFalse(event._flag)

    def test_wait(self):
        event = gruvi.Event()
        done = []
        def waiter():
            done.append(False)
            event.wait()
            done.append(True)
        gruvi.spawn(waiter)
        gruvi.sleep(0)
        self.assertEqual(done, [False])
        event.set()
        gruvi.sleep(0)
        self.assertEqual(done, [False, True])


class TestCondition(UnitTest):

    def test_basic(self):
        # Ensure that a basic wait/notify works.
        cond = gruvi.Condition()
        waiting = [0]
        def wait_cond():
            with cond:
                waiting[0] += 1
                cond.wait()
                waiting[0] -= 1
        gruvi.spawn(wait_cond)
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 1)
        with cond:
            cond.notify()
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 0)

    def test_notify_multiple(self):
        # Ensure that multiple fibers can be notified, and that the order in
        # which they are notified is respected.
        cond = gruvi.Condition()
        waiting = [0]
        done = []
        def wait_cond(i):
            with cond:
                waiting[0] += 1
                cond.wait()
                waiting[0] -= 1
                done.append(i)
        fibers = []
        for i in range(10):
            fibers.append(gruvi.spawn(wait_cond, i))
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 10)
        with cond:
            cond.notify(1)
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 9)
        with cond:
            cond.notify(3)
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 6)
        with cond:
            cond.notify_all()
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 0)
        self.assertEqual(done, list(range(10)))

    def test_wait_for(self):
        # Ensure that wait_for can wait for a predicate
        cond = gruvi.Condition()
        waiting = [0]
        unblock = []
        done = []
        def wait_cond(i):
            with cond:
                waiting[0] += 1
                cond.wait_for(lambda: i in unblock)
                waiting[0] -= 1
                done.append(i)
        fibers = []
        for i in range(10):
            fibers.append(gruvi.spawn(wait_cond, i))
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 10)
        with cond:
            cond.notify(1)  # no predicate matches
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 10)
        unblock += [0]
        with cond:
            cond.notify(1)  # one predicate matches
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 9)
        unblock += [2, 3]
        with cond:
            cond.notify(3)  # two match
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 7)
        unblock += [1]
        with cond:
            cond.notify_all()  # one match
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 6)
        unblock += list(range(10))
        with cond:
            cond.notify_all()  # one match
        gruvi.sleep(0)
        self.assertEqual(waiting[0], 0)
        self.assertEqual(done, [0, 2, 3, 1, 4, 5, 6, 7, 8, 9])

    def test_call_without_lock(self):
        # A RuntimeError should be raised if notify or wait are called without
        # the lock.
        cond = gruvi.Condition()
        self.assertRaises(RuntimeError, cond.wait)
        self.assertRaises(RuntimeError, cond.notify)

    def test_wait_timeout(self):
        # When a timeout occurs, wait() should return False
        cond = gruvi.Condition()
        with cond:
            self.assertFalse(cond.wait(timeout=0.01))
        self.assertFalse(cond._waiters)

    def test_wait_for_timeout(self):
        # When a timeout occurs, wait_for() should return False
        cond = gruvi.Condition()
        waiters = [0]
        def notify_cond():
            with cond:
                waiters[0] += 1
                cond.notify()
                waiters[0] -= 1
        gruvi.spawn(notify_cond)
        with cond:
            self.assertEqual(waiters[0], 0)
            self.assertFalse(cond.wait_for(lambda: False, timeout=0.1))
            self.assertEqual(waiters[0], 0)


class TestQueue(UnitTest):

    def test_basic(self):
        # What is put in the queue, should come out.
        queue = gruvi.Queue()
        queue.put(10)
        self.assertEqual(queue.get(), 10)

    def test_types(self):
        # Queue should support putting in arbitrary objects.
        queue = gruvi.Queue()
        queue.put('foo')
        self.assertEqual(queue.get(), 'foo')
        queue.put(['foo'])
        self.assertEqual(queue.get(), ['foo'])

    def test_order(self):
        # The behavior of a queue should be FIFO
        queue = gruvi.Queue()
        for i in range(10):
            queue.put(10+i)
        for i in range(10):
            self.assertEqual(queue.get(), 10+i)

    def test_qsize(self):
        # The qsize() of a queue should by default be the number of elements
        queue = gruvi.Queue()
        for i in range(10):
            queue.put(10+i)
            self.assertEqual(queue.qsize(), i+1)
        for i in range(10):
            self.assertEqual(queue.get(), 10+i)
            self.assertEqual(queue.qsize(), 10-i-1)

    def test_qsize_custom_size(self):
        # The put() method has an optional "size" argument that allows you to
        # specify a custom size.
        queue = gruvi.Queue()
        for i in range(10):
            queue.put(10+i, size=2)
            self.assertEqual(queue.qsize(), 2*(i+1))
        for i in range(10):
            self.assertEqual(queue.get(), 10+i)
            self.assertEqual(queue.qsize(), 2*(10-i-1))

    def test_get_wait(self):
        # Queue.get() should wait until an item becomes available.
        queue = gruvi.Queue()
        def put_queue(value):
            gruvi.sleep(0.01)
            queue.put(value)
        gruvi.spawn(put_queue, 'foo')
        self.assertEqual(queue.get(), 'foo')

    def test_get_timeout(self):
        # Ensure the "timeout" argument to Queue.get() works
        queue = gruvi.Queue()
        hub = get_hub()
        t0 = hub.loop.now()
        self.assertRaises(gruvi.QueueEmpty, queue.get, timeout=0.01)
        t1 = hub.loop.now()
        self.assertGreaterEqual(t1-t0, 10)

    def test_get_non_blocking(self):
        # Ensure the "block" argument to Queue.get() works
        queue = gruvi.Queue()
        self.assertRaises(gruvi.QueueEmpty, queue.get, block=False)
        self.assertRaises(gruvi.QueueEmpty, queue.get_nowait)

    def test_put_timeout(self):
        # Ensure the "timeout" argument to Queue.put() works
        queue = gruvi.Queue(maxsize=10)
        queue.put('foo', size=10)
        hub = get_hub()
        t0 = hub.loop.now()
        self.assertRaises(gruvi.QueueFull, queue.put, 'bar', timeout=0.01)
        t1 = hub.loop.now()
        self.assertGreaterEqual(t1-t0, 10)

    def test_put_non_blocking(self):
        # Ensure the "block" argument to Queue.put() works
        queue = gruvi.Queue(maxsize=10)
        queue.put('foo', size=10)
        self.assertRaises(gruvi.QueueFull, queue.put, 'bar', block=False)
        self.assertRaises(gruvi.QueueFull, queue.put_nowait, 'bar')

    def test_empty(self):
        # Ensure that empty() returns nonzero if the queue is empty.
        queue = gruvi.Queue()
        self.assertTrue(queue.empty())
        queue.put('foo')
        self.assertFalse(queue.empty())

    def test_full(self):
        # Ensure that empty() returns nonzero if the queue is empty.
        queue = gruvi.Queue(maxsize=1)
        self.assertFalse(queue.full())
        queue.put('foo')
        self.assertTrue(queue.full())

    def test_produce_consume(self):
        # Ensure that there's no deadlocks when pushing a large number of items
        # through a queue with a fixed size.
        queue = gruvi.Queue(maxsize=10)
        result = []; sizes = []
        def consumer(n):
            for i in range(n):
                queue.put(i)
                sizes.append(queue.qsize())
        def producer(n):
            for i in range(n):
                result.append(queue.get())
                sizes.append(queue.qsize())
        ni = 2000
        fcons = gruvi.spawn(consumer, ni)
        fprod = gruvi.spawn(producer, ni)
        fcons.join(); fprod.join()
        self.assertEqual(len(result), ni)
        self.assertEqual(result, list(range(ni)))
        self.assertLessEqual(max(sizes), 10)

    def test_thread_safety(self):
        # A Queue should be thread safe. This meanst that all entries that are
        # put in the queue must be returned, that no entry must be returned
        # twice and that the order must be respected. Also no deadlock must
        # ever occur.
        # To test, fire up a bunch of threads which each fire up a bunch of
        # fibers, and have the fibers do some random sleeps. Then let it run
        # and test the result.
        result = []
        reference = []
        lock = gruvi.Lock()
        def put_queue(tid, fid, count):
            for i in range(count):
                with lock:
                    gruvi.sleep(random.randint(0, 10)/10000)
                    queue.put((tid, fid, count))
                    reference.append((tid, fid, count))
        def get_queue(count):
            for i in range(count):
                with lock:
                    result.append(queue.get())
        def thread_put(tid, nfibers, count):
            fibers = []
            for i in range(nfibers):
                fibers.append(gruvi.spawn(put_queue, tid, i, count))
            for fib in fibers:
                fib.join()
            gruvi.get_hub().close()
        def thread_get(nfibers, count):
            fibers = []
            for i in range(nfibers):
                fibers.append(gruvi.spawn(get_queue, count))
            for fib in fibers:
                fib.join()
            gruvi.get_hub().close()
        queue = gruvi.Queue()
        threads = []
        # 5 procuders and 5 consumers, each with 20 fibers
        for i in range(5):
            thread = threading.Thread(target=thread_put, args=(i, 20, 5))
            thread.start()
            threads.append(thread)
        for i in range(5):
            thread = threading.Thread(target=thread_get, args=(20, 5))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        gruvi.sleep(0)  # run callbacks
        self.assertEqual(len(result), 500)
        self.assertEqual(result, reference)
        # Within a (tid,fid) pair, the counts must be monotonic
        partial_sort = sorted(result, key=lambda el: (el[0], el[1]))
        full_sort = sorted(result, key=lambda el: (el[0], el[1], el[2]))
        self.assertEqual(partial_sort, full_sort)


class TestLifoQueue(UnitTest):

    def test_order(self):
        # The behavior of a queue should be LIFO
        queue = gruvi.LifoQueue()
        for i in range(10):
            queue.put(10+i)
        for i in range(10):
            self.assertEqual(queue.get(), 19-i)


class TestPriorityQueue(UnitTest):

    def test_order(self):
        # The queue should respect the priority we give it.
        queue = gruvi.PriorityQueue()
        items = list(range(100))
        prios = list(range(100))
        random.shuffle(prios)
        items = list(zip(prios, items))
        for item in items:
            queue.put(item)
        result = []
        for i in range(len(items)):
            result.append(queue.get())
        self.assertEqual(sorted(items), result)


if __name__ == '__main__':
    unittest.main()
