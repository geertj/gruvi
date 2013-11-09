#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function, division

import gc
import time
import random
import threading
import weakref

import gruvi
from gruvi import util, compat
from support import *


def lock_unlock(lock, count=50):
    failed = 0
    for i in range(count):
        # the granularity of libuv's timers is 1ms. the statement below
        # therefore sleeps 0ms 75% of the time, and 1ms 25% of the time.
        util.sleep(random.randint(0, 12)/10000)
        lock.acquire()
        util.sleep(random.randint(0, 12)/10000)
        failed += (1 if lock.locked != 1 else 0)
        lock.release()
    return failed


def lock_unlock_recursive(lock, count=10):
    failed = 0
    for i in range(count):
        util.sleep(random.randint(0, 12)/10000)
        lock.acquire()
        util.sleep(random.randint(0, 12)/10000)
        failed += (1 if lock.locked != 1 else 0)
        lock.acquire()
        util.sleep(random.randint(0, 12)/10000)
        failed += (1 if lock.locked != 2 else 0)
        lock.release()
        util.sleep(random.randint(0, 12)/10000)
        failed += (1 if lock.locked != 1 else 0)
        lock.release()
    return failed


class TestLock(UnitTest):

    def test_basic(self):
        lock = gruvi.Lock()
        self.assertFalse(lock.locked)
        lock.acquire()
        self.assertTrue(lock.locked)
        lock.release()
        self.assertFalse(lock.locked)

    def test_acquire_release(self):
        lock = gruvi.Lock()
        lock.acquire()
        lock.release()
        lock.acquire()
        self.assertTrue(lock.locked)
        lock.release()
        self.assertFalse(lock.locked)

    def test_context_manager(self):
        lock = gruvi.Lock()
        with lock:
            self.assertTrue(lock.locked)
        self.assertFalse(lock.locked)

    def test_acquire_multiple(self):
        lock = gruvi.Lock()
        lock.acquire()
        self.assertTrue(lock.locked)
        self.assertRaises(RuntimeError, lock.acquire)
        self.assertTrue(lock.locked)
        self.assertRaises(RuntimeError, lock.acquire)

    def test_release_multiple(self):
        lock = gruvi.Lock()
        self.assertRaises(RuntimeError, lock.release)
        self.assertFalse(lock.locked)
        lock.acquire()
        lock.release()
        self.assertFalse(lock.locked)
        self.assertRaises(RuntimeError, lock.release)
        self.assertFalse(lock.locked)

    def test_acquire_multiple_recursive(self):
        lock = gruvi.Lock(recursive=True)
        lock.acquire()
        self.assertTrue(lock.locked)
        lock.acquire()
        self.assertTrue(lock.locked)
        lock.release()
        self.assertTrue(lock.locked)
        lock.release()
        self.assertFalse(lock.locked)

    def test_acquire_release_threads(self):
        failed = [0]
        def thread_lock():
            lock.acquire()
            failed[0] += (1 if lock.locked != 1 else 0)
        def thread_unlock():
            time.sleep(0.1)
            lock.release()
            failed[0] += (1 if lock.locked != 0 else 0)
        t1 = threading.Thread(target=thread_lock)
        t2 = threading.Thread(target=thread_unlock)
        self.assertEqual(failed[0], 0)

    def test_acquire_release_threads_recursive(self):
        failed = [0]
        def thread_lock():
            lock.acquire()
            failed[0] += (1 if lock.locked != 1 else 0)
            lock.acquire()
            failed[0] += (1 if lock.locked != 2 else 0)
        def thread_unlock():
            time.sleep(0.1)
            lock.release()
            failed[0] += (1 if lock.locked != 1 else 0)
            lock.release()
            failed[0] += (1 if lock.locked != 0 else 0)
        t1 = threading.Thread(target=thread_lock)
        t2 = threading.Thread(target=thread_unlock)
        self.assertEqual(failed[0], 0)

    def test_fiber_safety(self):
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
            if fib.alive:
                fib.done.wait()
        self.assertEqual(failed[0], 0)

    def test_fiber_safety_recursive(self):
        lock = gruvi.Lock(recursive=True)
        failed = [0]
        def run_test():
            failed[0] += lock_unlock_recursive(lock, 10)
        fibers = []
        for i in range(20):
            fiber = gruvi.Fiber(run_test)
            fiber.start()
            fibers.append(fiber)
        for fib in fibers:
            if fib.alive:
                fib.done.wait()
        self.assertEqual(failed[0], 0)

    def test_thread_safety(self):
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
                if fib.alive:
                    fib.done.wait()
        threads = []
        for i in range(5):
            thread = threading.Thread(target=run_thread)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        self.assertEqual(failed[0], 0)

    def test_thread_safety_recursive(self):
        lock = gruvi.Lock(recursive=True)
        failed = [0]
        def run_test():
            failed[0] += lock_unlock_recursive(lock, 10)
        def run_thread():
            fibers = []
            for i in range(5):
                fiber = gruvi.Fiber(run_test)
                fiber.start()
                fibers.append(fiber)
            for fib in fibers:
                if fib.alive:
                    fib.done.wait()
        threads = []
        for i in range(5):
            thread = threading.Thread(target=run_thread)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        self.assertEqual(failed[0], 0)


class TestSignal(UnitTest):

    def test_basic(self):
        signal = gruvi.Signal()
        hub = gruvi.get_hub()
        hub.run_callback(lambda: signal.emit())
        value = signal.wait(timeout=0.1)
        self.assertEqual(value, ())

    def test_pass_value(self):
        signal = gruvi.Signal()
        hub = gruvi.get_hub()
        hub.run_callback(lambda: signal.emit(1))
        value = signal.wait()
        self.assertEqual(value, (1,))
        hub.run_callback(lambda: signal.emit(1, 2))
        value = signal.wait()
        self.assertEqual(value, (1, 2))

    def test_connect(self):
        result = []
        def callback(*args):
            result.append(args)
        signal = gruvi.Signal()
        signal.connect(callback)
        signal.emit()
        gruvi.util.sleep(0)
        self.assertEqual(result, [()])

    def test_connect_args(self):
        result = []
        def callback(*args):
            result.append(args)
        signal = gruvi.Signal()
        signal.connect(callback)
        signal.emit(1)
        signal.emit(1, 2)
        gruvi.util.sleep(0)
        self.assertEqual(result, [(1,), (1,2)])

    def test_disconnect(self):
        result = []
        def callback(*args):
            result.append(args)
        signal = gruvi.Signal()
        signal.connect(callback)
        signal.emit(1)
        signal.disconnect(callback)
        signal.emit(2)
        signal.connect(callback)
        signal.emit(3)
        gruvi.util.sleep(0)
        self.assertEqual(result, [(1,), (3,)])

    def test_thread_safety(self):
        result = [0]
        def thread_emit():
            gruvi.sleep(random.randint(0, 12)/10000)
            with signal.lock:
                signal.emit(1)
            gruvi.get_hub().close()
        def thread_wait():
            gruvi.sleep(random.randint(0, 12)/10000)
            res = signal.wait()
            result[0] += res[0]
            gruvi.get_hub().close()
        signal = gruvi.Signal()
        for i in range(100):
            t1 = threading.Thread(target=thread_emit)
            t2 = threading.Thread(target=thread_wait)
            with signal.lock:
                t1.start(); t2.start()
                t1.join(); t2.join()
                self.assertTrue(signal.lock.locked)
            self.assertFalse(signal.lock.locked)
            self.assertEqual(result[0], i+1)


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

    def test_fifo(self):
        # The default behavior of a queue should be FIFO
        queue = gruvi.Queue()
        for i in range(10):
            queue.put(10+i)
        for i in range(10):
            self.assertEqual(queue.get(), 10+i)

    def test_prio(self):
        # The constructor should take a priofunc argument which is a function
        # that returns the priority of an item. When getting elements from the
        # queue, the element with the highest priority should be returned first.
        queue = gruvi.Queue(priofunc=lambda el: len(el))
        for i in range(10):
            queue.put(i * 'x')
        for i in range(10):
            self.assertEqual(queue.get(), (10-i-1) * 'x')

    def test_len(self):
        # The len() of a queue should reflect the number of elements
        queue = gruvi.Queue()
        for i in range(10):
            queue.put(10+i)
            self.assertEqual(len(queue), i+1)
        for i in range(10):
            self.assertEqual(queue.get(), 10+i)
            self.assertEqual(len(queue), 10-i-1)

    def test_size_default(self):
        # The size() of a queue should by default be the number of elements
        queue = gruvi.Queue()
        for i in range(10):
            queue.put(10+i)
            self.assertEqual(queue.size(), i+1)
        for i in range(10):
            self.assertEqual(queue.get(), 10+i)
            self.assertEqual(queue.size(), 10-i-1)

    def test_size_double(self):
        # The queue constructor should take a sizefunc argument that is a
        # function that returns the size of an item. The total size() of the
        # queue should be the sum of the element sizes.
        queue = gruvi.Queue(sizefunc=lambda el: 2)
        for i in range(10):
            queue.put(10+i)
            self.assertEqual(queue.size(), 2*(i+1))
        for i in range(10):
            self.assertEqual(queue.get(), 10+i)
            self.assertEqual(queue.size(), 2*(10-i-1))

    def test_size_changed(self):
        # The size_changed signal should be emitted for every item that is
        # added and removed.
        queue = gruvi.Queue()
        events = []
        def callback(oldsz, newsz):
            events.append((oldsz, newsz))
        queue.size_changed.connect(callback)
        for i in range(10):
            queue.put(i)
        for i in range(10):
            queue.get(i)
        gruvi.sleep(0)  # allow callbacks to run
        check = list(zip(range(0, 10), range(1, 11)))
        check += list(zip(range(10, 0, -1), range(9, -1, -1)))
        self.assertEqual(events, check)

    def test_wait(self):
        # Queue.get() should wait until an item becomes available.
        queue = gruvi.Queue()
        def put_queue(value):
            gruvi.sleep(0.01)
            queue.put(value)
        fib = gruvi.Fiber(put_queue, ('foo',))
        fib.start()
        self.assertEqual(queue.get(), 'foo')

    def test_thread_safety(self):
        # When using the lock, a Queue should be thread safe. This meanst that
        # all entries that are put in the queue must be returned, that no entry
        # must be returned twice, that the order must be respected, and that
        # the size_changed signals are fired in the right order. Also no
        # deadlock must occur.
        # To test, fire up a bunch of threads which each fire up a bunch of
        # fibers, and have the fibers do some random sleeps. Then let it run
        # and test the result.
        result = []
        events = []
        order  = []
        def callback(oldsz, newsz):
            events.append(1 if newsz > oldsz else -1)
        def put_queue(tid, fid, count):
            for i in range(count):
                with queue.lock:
                    gruvi.sleep(random.randint(0, 12)/10000)
                    queue.put((tid, fid, count))
                    order.append(1)
        def get_queue(count):
            for i in range(count):
                with queue.lock:
                    result.append(queue.get())
                    order.append(-1)
        def thread_put(tid, nfibers, count):
            fibers = []
            for i in range(nfibers):
                fiber = gruvi.Fiber(put_queue, (tid,i,count))
                fiber.start()
                fibers.append(fiber)
            for fib in fibers:
                if fib.alive:
                    fib.done.wait()
            gruvi.get_hub().close()
        def thread_get(nfibers, count):
            fibers = []
            for i in range(nfibers):
                fiber = gruvi.Fiber(get_queue, (count,))
                fiber.start()
                fibers.append(fiber)
            for fib in fibers:
                if fib.alive:
                    fib.done.wait()
            gruvi.get_hub().close()
        queue = gruvi.Queue()
        queue.size_changed.connect(callback)
        threads = []
        for i in range(5):
            thread = threading.Thread(target=thread_put, args=(i,10,5))
            thread.start()
            threads.append(thread)
        for i in range(5):
            thread = threading.Thread(target=thread_get, args=(10,5))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        gruvi.sleep(0)  # run callbacks
        self.assertEqual(len(result), 250)
        # Within a (tid,fid) pair, the counts must be monotonic
        partial_sort = sorted(result, key=lambda el: (el[0], el[1]))
        full_sort = sorted(result, key=lambda el: (el[0], el[1], el[2]))
        self.assertEqual(partial_sort, full_sort)
        # The order of the size_changed signals must be the order of put()/add().
        self.assertEqual(sum(events), 0)
        self.assertEqual(events, order)


class TestWait(UnitTest):

    def test_basic(self):
        # wait() should be able to wait for any signal passed to it.
        signals = [gruvi.Signal() for i in range(10)]
        def emit_signal(n):
            signals[n].emit(n)
        for i in range(10):
            fib = gruvi.Fiber(emit_signal, (i,))
            fib.start()
            result = gruvi.wait(signals)
            self.assertEqual(result, (signals[i], i))

    def test_timeout(self):
        # A timeout should raise a Timeout exception.
        signals = [gruvi.Signal()]
        self.assertRaises(gruvi.Timeout, gruvi.wait, signals, timeout=0)
        self.assertRaises(gruvi.Timeout, gruvi.wait, signals, timeout=0.001)

    def test_timeout_cleanup(self):
        # After a timeout, the internal callback set up by wait() should be
        # disconnected from all signals.
        signals = [gruvi.Signal(), gruvi.Signal()]
        self.assertRaises(gruvi.Timeout, gruvi.wait, signals, timeout=0.001)
        self.assertEqual(signals[0].callbacks, [])
        self.assertEqual(signals[1].callbacks, [])


class TestWaitAll(UnitTest):

    def test_basic(self):
        # A basic functionality test raising 10 signals. All signals should be
        # returned, in the order emitted.
        signals = [gruvi.Signal() for i in range(10)]
        def emit_signals():
            for ix,sig in enumerate(signals):
                sig.emit(ix)
        fib = gruvi.Fiber(emit_signals)
        fib.start()
        result = list(gruvi.waitall(signals))
        self.assertEqual(len(result), len(signals))
        for ix,res in enumerate(result):
            self.assertIsInstance(res[0], gruvi.Signal)
            self.assertEqual(res[1], ix)

    def test_order(self):
        # The order returned should be the order raised, not order passed.
        signals = [gruvi.Signal() for i in range(10)]
        def emit_signals():
            for ix,sig in enumerate(reversed(signals)):
                sig.emit(ix)
        fib = gruvi.Fiber(emit_signals)
        fib.start()
        result = list(gruvi.waitall(signals))
        self.assertEqual(len(result), len(signals))
        for ix,res in enumerate(result):
            self.assertIsInstance(res[0], gruvi.Signal)
            self.assertEqual(res[1], ix)

    def test_wait(self):
        # Introduce a delay between the emission of the signals.
        signals = [gruvi.Signal() for i in range(10)]
        def emit_signals():
            for ix,sig in enumerate(signals):
                gruvi.sleep(0.001)
                sig.emit(ix)
        fib = gruvi.Fiber(emit_signals)
        fib.start()
        result = list(gruvi.waitall(signals))
        self.assertEqual(len(result), len(signals))
        for ix,res in enumerate(result):
            self.assertIsInstance(res[0], gruvi.Signal)
            self.assertEqual(res[1], ix)

    def test_emit_many(self):
        # Emit each signal multiple times. Every signal should be returned once.
        signals = [gruvi.Signal() for i in range(10)]
        def emit_signals():
            for ix,sig in enumerate(signals):
                sig.emit(ix)
                sig.emit(ix)
            for ix,sig in enumerate(signals):
                sig.emit(ix)
                sig.emit(ix)
        fib = gruvi.Fiber(emit_signals)
        fib.start()
        result = list(gruvi.waitall(signals))
        self.assertEqual(len(result), len(signals))
        for ix,res in enumerate(result):
            self.assertIsInstance(res[0], gruvi.Signal)
            self.assertEqual(res[1], ix)

    def test_timeout(self):
        # Timeout after a few signals.
        signals = [gruvi.Signal() for i in range(10)]
        def emit_signals():
            for ix,sig in enumerate(signals):
                if ix == len(signals)//2:
                    gruvi.sleep(0.2)
                sig.emit(ix)
        fib = gruvi.Fiber(emit_signals)
        fib.start()
        result = []
        exc = None
        try:
            for res in gruvi.waitall(signals, timeout=0.1):
                result.append(res)
        except gruvi.Timeout as e:
            exc = e
        self.assertIsInstance(exc, gruvi.Timeout)
        self.assertEqual(len(result), len(signals)//2)

    def test_cancel(self):
        # Cancel the generator after a few signals.
        signals = [gruvi.Signal() for i in range(10)]
        def emit_signals():
            for ix,sig in enumerate(signals):
                sig.emit(ix)
        fib = gruvi.Fiber(emit_signals)
        fib.start()
        result = []
        gen = gruvi.waitall(signals)
        for i in range(len(signals)//2):
            result = compat.next(gen)
        gen.close()
        self.assertRaises(StopIteration, compat.next, gen)

    def test_cleanup_timeout(self):
        # Unfired signals should be disconnected after a timeout.
        signals = [gruvi.Signal(), gruvi.Signal()]
        gen = gruvi.waitall(signals, timeout=0.1)
        self.assertRaises(gruvi.Timeout, compat.next, gen)
        self.assertEqual(signals[0].callbacks, [])
        self.assertEqual(signals[1].callbacks, [])

    def test_cleanup_cancel(self):
        # Unfired signals should be disconnected after the generator is
        # cancelled.
        signals = [gruvi.Signal(), gruvi.Signal()]
        gen = gruvi.waitall(signals)
        gen.close()
        self.assertEqual(signals[0].callbacks, [])
        self.assertEqual(signals[1].callbacks, [])


if __name__ == '__main__':
    unittest.main(buffer=True)
