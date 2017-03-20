#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function, division

import random
import unittest

import gruvi
from gruvi import Fiber, Event, Process, Timeout
from gruvi.futures import FiberPool, ThreadPool, Future
from support import UnitTest


class TestFuture(UnitTest):

    def test_result(self):
        fut = Future()
        fut.set_result(10)
        self.assertEqual(fut.result(), 10)
        self.assertIsNone(fut.exception())
        self.assertEqual(fut.result(), 10)

    def test_exception(self):
        fut = Future()
        fut.set_exception(ValueError())
        self.assertIsInstance(fut.exception(), ValueError)
        self.assertRaises(ValueError, fut.result)

    def test_wait_result(self):
        fut = Future()
        def set_result():
            gruvi.sleep(0.1)
            fut.set_result('foo')
        fib = gruvi.Fiber(set_result)
        fib.start()
        self.assertEqual(fut.result(), 'foo')

    def test_wait_result_timeout(self):
        fut = Future()
        self.assertRaises(gruvi.Timeout, fut.result, 0.01)

    def test_wait_exception(self):
        fut = Future()
        def set_result():
            gruvi.sleep(0.1)
            fut.set_exception(RuntimeError)
        fib = gruvi.Fiber(set_result)
        fib.start()
        self.assertEqual(fut.exception(), RuntimeError)

    def test_wait_exception_timeout(self):
        fut = Future()
        self.assertRaises(gruvi.Timeout, fut.exception, 0.01)

    def test_set_running(self):
        fut = Future()
        self.assertFalse(fut.running())
        fut.set_running()
        self.assertTrue(fut.running())

    def test_cancel(self):
        fut = Future()
        self.assertFalse(fut.cancelled())
        self.assertTrue(fut.cancel())
        self.assertTrue(fut.cancelled())

    def test_cancel_running(self):
        fut = Future()
        self.assertFalse(fut.cancelled())
        fut.set_running(True)
        self.assertTrue(fut.running())
        self.assertTrue(fut.cancel())
        self.assertTrue(fut.cancelled())

    def test_cancel_running_nocancel(self):
        fut = Future()
        self.assertFalse(fut.cancelled())
        fut.set_running(False)
        self.assertTrue(fut.running())
        self.assertFalse(fut.cancel())
        self.assertFalse(fut.cancelled())

    def test_set_result_twice(self):
        fut = Future()
        fut.set_result('foo')
        self.assertEqual(fut.result(), 'foo')
        fut.set_result('bar')
        self.assertEqual(fut.result(), 'foo')

    def test_set_exception_twice(self):
        fut = Future()
        fut.set_exception(RuntimeError)
        self.assertEqual(fut.exception(), RuntimeError)
        fut.set_exception(ValueError)
        self.assertEqual(fut.exception(), RuntimeError)

    def test_set_running_twice(self):
        fut = Future()
        fut.set_running(False)
        state = fut._state
        fut.set_running(True)
        self.assertEqual(state, fut._state)

    def test_callbacks(self):
        cbargs = []
        def callback(*args):
            cbargs.append(args)
        fut = Future()
        fut.add_done_callback(callback)
        fut.add_done_callback(callback, 'foo')
        fut.add_done_callback(callback, 'foo', 'bar')
        fut.add_done_callback(callback, fut)
        handle = fut.add_done_callback(callback, 'baz')
        self.assertIsNotNone(handle)
        fut.remove_done_callback(handle)
        fut.set_result('quz')
        self.assertEqual(len(cbargs), 4)
        self.assertEqual(cbargs[0], ())
        self.assertEqual(cbargs[1], ('foo',))
        self.assertEqual(cbargs[2], ('foo', 'bar'))
        self.assertEqual(cbargs[3], (fut,))


class PoolTest(object):

    def setUp(self):
        self.pool = self.Pool(self.maxsize)

    def tearDown(self):
        self.pool.close()

    def test_simple(self):
        def func(val):
            return val
        fut = self.pool.submit(func, 'foo')
        self.assertIsInstance(fut, Future)
        self.assertEqual(fut.result(), 'foo')

    def test_submit_sleep(self):
        def func(val):
            gruvi.sleep(0.1)
            return val
        fut = self.pool.submit(func, 'foo')
        self.assertEqual(fut.result(), 'foo')

    def test_submit_many(self):
        def func(val):
            return val
        futures = []
        for i in range(self.count):
            futures.append(self.pool.submit(func, i))
        result = []
        for fut in futures:
            result.append(fut.result())
        result.sort()
        self.assertEqual(result, list(range(self.count)))

    def test_submit_many_sleep(self):
        def func(val):
            gruvi.sleep(0.01)
            return val
        futures = []
        for i in range(self.count):
            futures.append(self.pool.submit(func, i))
        result = []
        for fut in futures:
            result.append(fut.result())
        result.sort()
        self.assertEqual(result, list(range(self.count)))

    def test_submit_exception(self):
        def func():
            raise ValueError()
        fut = self.pool.submit(func)
        self.assertRaises(ValueError, fut.result)

    def test_map(self):
        def double(x):
            return x*2
        result = self.pool.map(double, range(self.count))
        self.assertEqual(list(result), list(range(0, 2*self.count, 2)))

    def test_map_order(self):
        # Make sure that map() respects the order of the input. The random
        # delay in double() will make the results ready out of order, but the
        # return value of map() should be in order nonetheless.
        def double(x):
            gruvi.sleep(random.randint(0, 2) / 1000)
            return x*2
        result = self.pool.map(double, range(self.count))
        self.assertEqual(list(result), list(range(0, 2*self.count, 2)))

    def test_map_timeout(self):
        # Ensure that the "timeout" argument to map() works.
        result = self.pool.map(gruvi.sleep, (0.2,), timeout=0.1)
        self.assertRaises(gruvi.Timeout, list, result)

    def test_pool_close(self):
        def func(i):
            return i
        pool = self.Pool()
        futures = []
        for i in range(self.count):
            futures.append(pool.submit(func, i))
        result = [fut.result() for fut in futures]
        result.sort()
        self.assertEqual(result, list(range(self.count)))
        self.assertGreater(len(pool._workers), 0)
        pool.close()
        self.assertEqual(len(pool._workers), 0)
        self.assertRaises(RuntimeError, pool.submit, func, i)
        self.assertRaises(RuntimeError, list, pool.map(func, [i]))


class TestFiberPool(PoolTest, UnitTest):

    maxsize = 50
    count = 100
    Pool = FiberPool


class TestThreadPool(PoolTest, UnitTest):

    maxsize = 5
    count = 100
    Pool = ThreadPool


class TestWait(UnitTest):

    def test_basic(self):
        # Simple wait() test waiting for two futures.
        futures = [Future() for i in range(2)]
        result = []
        def waiter():
            result.append(gruvi.wait(futures))
        fib = Fiber(waiter)
        fib.start()
        gruvi.sleep(0)
        self.assertTrue(fib.alive)
        self.assertEqual(result, [])
        futures[0].set_result(None)
        gruvi.sleep(0)
        self.assertTrue(fib.alive)
        futures[1].set_result(None)
        gruvi.sleep(0)
        self.assertFalse(fib.alive)
        self.assertEqual(result, [(futures, [])])

    def test_partial(self):
        # Ensure that the "count" argument of wait() can be used to wait for a
        # subset of the futures to complete.
        futures = [Future() for i in range(10)]
        result = []
        def waiter():
            result.append(gruvi.wait(futures, count=5))
        fib = Fiber(waiter)
        fib.start()
        gruvi.sleep(0)
        for i in range(4):
            futures[i].set_result(None)
        self.assertTrue(fib.alive)
        self.assertEqual(result, [])
        futures[4].set_result(None)
        gruvi.sleep(0)
        self.assertFalse(fib.alive)
        self.assertEqual(result, [(futures[:5], futures[5:])])

    def test_partial_fibers(self):
        # Have a lot of fibers wait on a small subet of a lot of futures.
        futures = [Future() for i in range(100)]
        def waiter():
            gruvi.wait(futures, count=2)
        fibers = [Fiber(waiter) for i in range(100)]
        for fib in fibers:
            fib.start()
        gruvi.sleep(0)
        futures[0].set_result(None)
        gruvi.sleep(0)
        for fib in fibers:
            self.assertTrue(fib.alive)
        futures[len(futures)//2].set_result(None)
        gruvi.sleep(0)
        for fib in fibers:
            self.assertFalse(fib.alive)
        # Test cleanup
        for fut in futures:
            self.assertFalse(fut._callbacks)

    def test_timeout(self):
        futures = [Future() for i in range(10)]
        result = gruvi.wait(futures, timeout=0.01)
        self.assertEqual(result, ([], futures))
        for fut in futures:
            self.assertFalse(fut._callbacks)

    def test_timeout_fibers(self):
        futures = [Future() for i in range(10)]
        result = []
        def waiter():
            result.append(gruvi.wait(futures, timeout=0.01))
        fibers = [Fiber(waiter) for i in range(10)]
        for fib in fibers:
            fib.start()
        for fib in fibers:
            fib.join()
        self.assertEqual(len(result), 10)
        for res in result:
            self.assertEqual(res, ([], futures))
        for fut in futures:
            self.assertFalse(fut._callbacks)

    def test_duplicate(self):
        futures = [Future()] * 5
        result = []
        def waiter():
            result.append(gruvi.wait(futures))
        fib = Fiber(waiter)
        fib.start()
        gruvi.sleep(0)
        self.assertEqual(result, [])
        futures[0].set_result(None)
        gruvi.sleep(0)
        self.assertEqual(result, [(futures, [])])

    def test_object_types(self):
        def sleeper():
            gruvi.sleep(0.1)
        objects = []
        for i in range(2):
            fib = Fiber(sleeper)
            fib.start()
            objects.append(fib)
        for i in range(2):
            objects.append(Event())
        for i in range(2):
            objects.append(Future())
        for i in range(2):
            proc = Process()
            proc.spawn('true')
            objects.append(proc)
        result = []
        def waiter():
            result.append(gruvi.wait(objects))
        fib = Fiber(waiter)
        fib.start()
        gruvi.sleep(0)
        self.assertTrue(fib.alive)
        objects[2].set()
        objects[3].set()
        objects[4].set_result(True)
        objects[5].set_exception(RuntimeError)
        fib.join()
        self.assertFalse(fib.alive)
        self.assertEqual(set(result[0][0]), set(objects))
        self.assertFalse(objects[0].alive)
        self.assertFalse(objects[1].alive)
        self.assertEqual(objects[6].returncode, 0)
        self.assertEqual(objects[7].returncode, 0)
        for obj in objects:
            self.assertFalse(obj._callbacks)
        objects[6].close()
        objects[7].close()


class TestAsCompleted(UnitTest):

    def test_order(self):
        futures = [Future() for i in range(100)]
        order = list(range(len(futures)))
        random.shuffle(order)
        futures[order[0]].set_result(None)
        count = 0
        for fut in gruvi.as_completed(futures):
            self.assertEqual(fut, futures[order[count]])
            count += 1
            if count < len(order):
                futures[order[count]].set_result(None)
        self.assertEqual(count, len(futures))
        for fut in futures:
            self.assertFalse(fut._callbacks)

    def test_partial(self):
        futures = [Future() for i in range(100)]
        futures[0].set_result(None)
        count = 0
        for fut in gruvi.as_completed(futures, 10):
            self.assertEqual(fut, futures[count])
            count += 1
            futures[count].set_result(None)
        self.assertEqual(count, 10)
        for fut in futures:
            self.assertFalse(fut._callbacks)

    def test_partial_fibers(self):
        futures = [Future() for i in range(100)]
        result = []
        def waiter():
            for fut in gruvi.as_completed(futures, count=2):
                result.append(fut)
        fibers = [Fiber(waiter) for i in range(100)]
        for fib in fibers:
            fib.start()
        gruvi.sleep(0)
        futures[0].set_result(None)
        for fib in fibers:
            self.assertTrue(fib.alive)
        futures[len(futures)//2].set_result(None)
        gruvi.sleep(0)
        for fib in fibers:
            self.assertFalse(fib.alive)
        self.assertEqual(len(result), len(fibers)*2)
        for fut in futures:
            self.assertFalse(fut._callbacks)

    def test_timeout(self):
        futures = [Future() for i in range(10)]
        self.assertRaises(Timeout, lambda: list(gruvi.as_completed(futures, timeout=0.01)))
        for fut in futures:
            self.assertFalse(fut._callbacks)

    def test_timeout_fibers(self):
        futures = [Future() for i in range(10)]
        exceptions = []
        def waiter():
            try:
                list(gruvi.as_completed(futures, timeout=0.01))
            except Timeout as e:
                exceptions.append(e)
        fibers = [Fiber(waiter) for i in range(10)]
        for fib in fibers:
            fib.start()
        for fib in fibers:
            fib.join()
        self.assertEqual(len(exceptions), 10)
        for exc in exceptions:
            self.assertIsInstance(exc, Timeout)
        for fut in futures:
            self.assertFalse(fut._callbacks)


if __name__ == '__main__':
    unittest.main()
