#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import gc
import time
import signal
import inspect
import threading
import weakref
import unittest
from unittest import SkipTest

import gruvi
from support import UnitTest


class TestHub(UnitTest):

    def test_switchpoint(self):
        # Wrapping a function in @switchpoint should return function with
        # proper docs and a proper signature. Calling it should call the
        # underlying function.
        def func(foo, bar, baz=None, *args, **kwargs):
            """Foo bar."""
            return (foo, bar, baz, args, kwargs)
        wrapper = gruvi.switchpoint(func)
        self.assertTrue(wrapper.__switchpoint__)
        while hasattr(wrapper, '__wrapped__'):
            wrapper = wrapper.__wrapped__
        self.assertEqual(wrapper.__name__, 'func')
        argspec = inspect.getargspec(wrapper)
        self.assertEqual(argspec.args, ['foo', 'bar', 'baz'])
        self.assertEqual(argspec.varargs, 'args')
        self.assertEqual(argspec.keywords, 'kwargs')
        self.assertEqual(argspec.defaults, (None,))
        result = wrapper(1, 2, qux='foo')
        self.assertEqual(result, (1, 2, None, (), {'qux': 'foo'}))
        result = wrapper(1, 2, 3, 4, qux='foo')
        self.assertEqual(result, (1, 2, 3, (4,), {'qux': 'foo'}))

    def test_sigint(self):
        # The Hub should exit on CTRL-C (SIGINT).
        # On windows, sending SIGINT kills all processes attached to a console,
        # including the test driver.
        if sys.platform.startswith('win'):
            raise SkipTest('test skipped on Windows')
        def send_sigint():
            time.sleep(0.01)
            os.kill(os.getpid(), signal.SIGINT)
        t1 = threading.Thread(target=send_sigint)
        t1.start()
        hub = gruvi.get_hub()
        hub.switch()
        self.assertFalse(hub.is_alive())
        t1.join()

    def test_get_new_hub(self):
        # When the hub is closed, get_hub() should return a new one.
        hub = gruvi.get_hub()
        hub.close()
        hub.switch()
        hub2 = gruvi.get_hub()
        self.assertIsNot(hub, hub2)

    def test_close(self):
        # Calling hub.close() should cause the hub to exit.
        hub = gruvi.Hub()
        hub.run_callback(hub.close)
        self.assertIsNone(hub.switch())
        self.assertFalse(hub.is_alive())

    def test_close_from_thread(self):
        # Calling hub.close() from a thread should cause the hub to exit.
        def close_hub():
            time.sleep(0.01)
            hub.close()
        t1 = threading.Thread(target=close_hub)
        t1.start()
        hub = gruvi.Hub()
        self.assertIsNone(hub.switch())
        self.assertFalse(hub.is_alive())
        t1.join()

    def test_cleanup(self):
        # After we close() a Hub, it should be garbage collectable, including
        # its event loop.
        hub = gruvi.Hub()
        gruvi.sleep(0)
        ref1 = weakref.ref(hub)
        ref2 = weakref.ref(hub.loop)
        hub.close()
        hub.switch()
        del hub
        gc.collect()
        self.assertIsNone(ref1())
        self.assertIsNone(ref2())

    def test_thread_close(self):
        # If we close() a Hub in a thread, it should be garbage collectable.
        refs = []
        def thread_sleep():
            hub = gruvi.get_hub()
            gruvi.sleep(0)
            refs.append(weakref.ref(hub))
            refs.append(weakref.ref(hub.loop))
            hub.close()
            hub.switch()
        t1 = threading.Thread(target=thread_sleep)
        refs.append(weakref.ref(t1))
        t1.start(); t1.join(); del t1
        gruvi.sleep(0.1)  # Give the thread time to exit.
        gc.collect()
        self.assertIsNone(refs[0]())
        self.assertIsNone(refs[1]())
        self.assertIsNone(refs[2]())

    def test_many_hubs(self):
        # Create and close a Hub in many threads. If the hub does not garbage
        # collect, then this will run out of file descriptors.
        for i in range(100):
            hub = gruvi.Hub()
            with gruvi.switch_back(timeout=0, hub=hub):
                self.assertRaises(gruvi.Timeout, hub.switch)
            hub.close()
            hub.switch()
            gc.collect()

    def test_callback_order(self):
        # Callbacks run with run_callback() should be run in the order they
        # were added.
        hub = gruvi.Hub()
        result = []
        for i in range(100):
            hub.run_callback(result.append, i)
        hub.close()
        hub.switch()
        self.assertEqual(len(result), 100)
        self.assertEqual(result, list(range(100)))

    def test_sleep(self):
        # Test that sleep() works
        hub = gruvi.get_hub()
        # use hub.now() as there's slight rounding errors with time.time()
        t0 = hub.loop.now()
        gruvi.sleep(0.01)
        t1 = hub.loop.now()
        self.assertGreaterEqual(t1-t0, 10)
        t0 = hub.loop.now()
        gruvi.sleep(0.1)
        t1 = hub.loop.now()
        self.assertGreaterEqual(t1-t0, 100)


class TestAssertNoSwitchpoints(UnitTest):

    def test_assert_no_switchpoints(self):
        # Calling a switchpoint while in an assert_no_switchpoints block should
        # raise an AssertionError.
        with gruvi.assert_no_switchpoints():
            self.assertRaises(AssertionError, gruvi.sleep, 0)


class TestSwitchBack(UnitTest):

    def test_call(self):
        # Calling a switch_back instance should cause hub.switch() to return
        # with an (args, kwargs) tuple.
        hub = gruvi.get_hub()
        with gruvi.switch_back() as switcher:
            hub.run_callback(lambda: switcher('foo', bar='baz'))
            self.assertEqual(hub.switch(), (('foo',), {'bar': 'baz'}))

    def test_timeout(self):
        # A timeout in a switch_back instance should cause hub.switch() to
        # raise a Timeout exception.
        hub = gruvi.get_hub()
        with gruvi.switch_back(0.01):
            self.assertRaises(gruvi.Timeout, hub.switch)

    def test_throw(self):
        # An exception thrown with the throw() method of a switch_back instance
        # should cause hub.switch to raise that exception.
        hub = gruvi.get_hub()
        with gruvi.switch_back() as switcher:
            hub.run_callback(lambda: switcher.throw(ValueError('foo')))
            exc = self.assertRaises(ValueError, hub.switch)
            self.assertEqual(exc.args[0], 'foo')


if __name__ == '__main__':
    unittest.main()
