#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import random

import gruvi
from gruvi.futures import *
from support import *


class TestFuture(UnitTest):

    def test_value(self):
        fut = Future()
        fut.set_result(10, None)
        self.assertEqual(fut.value, 10)
        self.assertIsNone(fut.exception)
        self.assertEqual(fut.result(), 10)

    def test_exception(self):
        fut = Future()
        err = ValueError()
        fut.set_result(None, err)
        self.assertIsNone(fut.value)
        self.assertTrue(fut.exception is err)
        self.assertRaises(ValueError, fut.result)

    def test_wait_signal(self):
        fut = Future()
        def set_result():
            gruvi.sleep(0.1)
            fut.set_result('foo')
        fib = gruvi.Fiber(set_result)
        fib.start()
        fut.done.wait()
        self.assertEqual(fut.value, 'foo')

    def test_wait_result(self):
        fut = Future()
        def set_result():
            gruvi.sleep(0.1)
            fut.set_result('foo')
        fib = gruvi.Fiber(set_result)
        fib.start()
        self.assertEqual(fut.result(), 'foo')


class PoolTest(object):

    def setUp(self):
        self.pool = self.Pool()

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
            gruvi.sleep(random.random() * 0.01)
            return x*2
        result = self.pool.map(double, range(self.count))
        self.assertEqual(list(result), list(range(0, 2*self.count, 2)))

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
        self.assertGreater(pool.size, 0)
        self.assertFalse(pool.closed)
        pool.close()
        self.assertEqual(pool.size, 0)
        self.assertTrue(pool.closed)


class TestFiberPool(PoolTest, UnitTest):

    count = 500
    Pool = FiberPool


class TestThreadPool(PoolTest, UnitTest):

    count = 50
    Pool = ThreadPool


if __name__ == '__main__':
    unittest.main(buffer=True)
