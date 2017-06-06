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
from gruvi.hub import _reinit_hub
from gruvi.fibers import Fiber
from support import UnitTest


class TestHub(UnitTest):

    def tearDown(self):
        # Some of our tests kill the hub so we re-init it here.
        _reinit_hub()
        super(TestHub, self).tearDown()

    def test_switchpoint(self):
        # Wrapping a function in @switchpoint should return function with
        # proper docs and a proper signature. Calling it should call the
        # underlying function.
        def func(foo, bar, baz=None, *args, **kwargs):
            """Foo bar."""
            return (foo, bar, baz, args, kwargs)
        wrapper = gruvi.switchpoint(func)
        self.assertTrue(wrapper.__switchpoint__)
        self.assertEqual(wrapper.__name__, 'func')
        # inspect.getargspec() returns a DeprecationWarning on Python 3.5+
        if hasattr(inspect, 'signature'):
            signature = inspect.signature(wrapper)
            pp = signature.parameters
            self.assertEqual(list(pp), ['foo', 'bar', 'baz', 'args', 'kwargs'])
            from inspect import Parameter
            self.assertEqual(pp['foo'].kind, Parameter.POSITIONAL_OR_KEYWORD)
            self.assertEqual(pp['foo'].default, Parameter.empty)
            self.assertEqual(pp['bar'].kind, Parameter.POSITIONAL_OR_KEYWORD)
            self.assertEqual(pp['bar'].default, Parameter.empty)
            self.assertEqual(pp['baz'].kind, Parameter.POSITIONAL_OR_KEYWORD)
            self.assertEqual(pp['baz'].default, None)
            self.assertEqual(pp['args'].kind, Parameter.VAR_POSITIONAL)
            self.assertEqual(pp['kwargs'].kind, Parameter.VAR_KEYWORD)
        else:
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
        # The Hub should raise a KeyboardError in the root fiber on CTRL-C (SIGINT).
        # On windows, sending SIGINT kills all processes attached to a console,
        # including the test driver. So skip this test on Windows.
        if sys.platform.startswith('win'):
            raise SkipTest('test skipped on Windows')
        def send_sigint():
            time.sleep(0.01)
            os.kill(os.getpid(), signal.SIGINT)
        t1 = threading.Thread(target=send_sigint)
        t1.start()
        hub = gruvi.get_hub()
        self.assertRaises(KeyboardInterrupt, hub.switch)
        self.assertTrue(hub.is_alive())
        t1.join()

    def test_close(self):
        # Calling hub.close() should cause the hub to exit.
        hub = gruvi.get_hub()
        gruvi.sleep(0.01)
        hub.close()
        self.assertFalse(hub.is_alive())

    def test_get_closed_hub(self):
        # When the hub is closed, get_hub() should still return the closed one
        hub = gruvi.get_hub()
        gruvi.sleep(0.01)
        hub.close()
        hub2 = gruvi.get_hub()
        self.assertIs(hub, hub2)

    def test_close_from_thread(self):
        # Calling hub.close() from a different thread should cause a RuntimeError
        exc = []
        hub = gruvi.get_hub()
        def close_hub():
            time.sleep(0.01)
            try:
                hub.close()
            except Exception as e:
                exc.append(e)
        t1 = threading.Thread(target=close_hub)
        t1.start(); t1.join()
        self.assertEqual(len(exc), 1)
        self.assertIsInstance(exc[0], RuntimeError)
        self.assertTrue(hub.is_alive())

    def test_cleanup(self):
        # After we close() a Hub, its event loop should be gc-able.
        hub = gruvi.get_hub()
        ref = weakref.ref(hub.loop)
        gruvi.sleep(0.01)
        hub.close()
        del hub
        gc.collect()
        self.assertIsNone(ref())

    def test_callback_order(self):
        # Callbacks run with run_callback() should be run in the order they
        # were added.
        hub = gruvi.get_hub()
        result = []
        for i in range(100):
            hub.run_callback(result.append, i)
        gruvi.sleep(0.01)
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
        fiber = Fiber(lambda: 'foo')
        with gruvi.assert_no_switchpoints():
            self.assertRaises(RuntimeError, fiber.switch)


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
