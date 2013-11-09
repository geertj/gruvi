#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import gc
import time
import inspect
import threading
import weakref

import pyuv
import gruvi
import gruvi.hub
from support import *


class TestHub(UnitTest):

    def test_switchpoint(self):
        def func(foo, bar, baz=None, *args, **kwargs):
            """Foo bar."""
            return (foo, bar, baz, args, kwargs)
        wrapper = gruvi.switchpoint(func)
        self.assertEqual(wrapper.__name__, 'func')
        self.assertTrue(wrapper.__doc__.endswith('switchpoint.*\n'))
        argspec = inspect.getargspec(wrapper)
        self.assertEqual(argspec.args, ['foo', 'bar', 'baz'])
        self.assertEqual(argspec.varargs, 'args')
        self.assertEqual(argspec.keywords, 'kwargs')
        self.assertEqual(argspec.defaults, (None,))
        result = wrapper(1, 2, qux='foo')
        self.assertEqual(result, (1, 2, None, (), { 'qux': 'foo'}))
        result = wrapper(1, 2, 3, 4, qux='foo')
        self.assertEqual(result, (1, 2, 3, (4,), { 'qux': 'foo'}))

    def test_hub_cleanup(self):
        # After we close() a Hub, it should be garbage collectable, including
        # its event loop.
        hub = gruvi.hub.Hub()
        gruvi.sleep(0)
        ref1 = weakref.ref(hub)
        ref2 = weakref.ref(hub.loop)
        hub.close()
        del hub
        gc.collect()
        self.assertIsNone(ref1())
        self.assertIsNone(ref2())

    def test_thread_cleanup(self):
        # If we close() a Hub in a thread, it should be garbage collectable.
        refs = []
        def thread_sleep():
            hub = gruvi.get_hub()
            gruvi.sleep(0)
            refs.append(weakref.ref(hub))
            refs.append(weakref.ref(hub.loop))
            hub.close()
        t1 = threading.Thread(target=thread_sleep)
        t1.start(); t1.join()
        del t1
        gc.collect()
        self.assertIsNone(refs[0]())
        self.assertIsNone(refs[1]())

    def test_many_hubs(self):
        # Create and close a Hub in many threads. If the hub does not garbage
        # collect, then this will run out of file descriptors.
        for i in range(100):
            hub = gruvi.hub.Hub()
            with gruvi.switch_back(timeout=0, hub=hub):
                self.assertRaises(gruvi.Timeout, hub.switch)
            hub.close()
            gc.collect()


if __name__ == '__main__':
    unittest.main(buffer=True)
