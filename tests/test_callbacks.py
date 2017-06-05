#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import unittest

from gruvi.dllist import dllist, Node
from gruvi.callbacks import add_callback, remove_callback, pop_callback
from gruvi.callbacks import walk_callbacks, run_callbacks
from gruvi.callbacks import has_callback, clear_callbacks
from support import UnitTest


class Object(object):

    def __init__(self):
        self._callbacks = None


class TestCallbacks(UnitTest):

    def test_add_pop_one(self):
        obj = Object()
        def callback(*args):
            pass
        add_callback(obj, callback)
        self.assertIsInstance(obj._callbacks, Node)
        self.assertIs(obj._callbacks.data, callback)
        self.assertEqual(obj._callbacks.extra, ())
        self.assertEqual(pop_callback(obj), (callback, ()))
        self.assertEqual(obj._callbacks, None)
        add_callback(obj, callback, (1, 2))
        self.assertIsInstance(obj._callbacks, Node)
        self.assertIs(obj._callbacks.data, callback)
        self.assertEqual(obj._callbacks.extra, (1, 2))
        self.assertEqual(pop_callback(obj), (callback, (1, 2)))
        self.assertEqual(obj._callbacks, None)

    def test_add_pop_multiple(self):
        obj = Object()
        def callback(*args):
            pass
        for i in range(5):
            add_callback(obj, callback)
        self.assertIsInstance(obj._callbacks, dllist)
        for i in range(5):
            self.assertEqual(len(obj._callbacks), 5-i)
            self.assertEqual(pop_callback(obj), (callback, ()))
        self.assertIsNone(obj._callbacks)
        for i in range(5):
            add_callback(obj, callback, (1, 2))
        self.assertIsInstance(obj._callbacks, dllist)
        for i in range(5):
            self.assertEqual(len(obj._callbacks), 5-i)
            self.assertEqual(pop_callback(obj), (callback, (1, 2)))
        self.assertIsNone(obj._callbacks)

    def test_add_remove_one(self):
        obj = Object()
        def callback(*args):
            pass
        handle = add_callback(obj, callback)
        self.assertIsInstance(obj._callbacks, Node)
        remove_callback(obj, handle)
        self.assertIs(obj._callbacks, None)

    def test_add_remove_multiple(self):
        obj = Object()
        def callback(*args):
            pass
        handles = []
        for i in range(5):
            handles.append(add_callback(obj, callback))
        self.assertIsInstance(obj._callbacks, dllist)
        for i in range(5):
            self.assertEqual(len(obj._callbacks), 5-i)
            remove_callback(obj, handles[i])
        self.assertIsNone(obj._callbacks)
        handles = []
        for i in range(5):
            handles.append(add_callback(obj, callback, (1, 2)))
        self.assertIsInstance(obj._callbacks, dllist)
        for i in range(5):
            self.assertEqual(len(obj._callbacks), 5-i)
            remove_callback(obj, handles[i])
        self.assertIsNone(obj._callbacks)

    def test_has_callback(self):
        obj = Object()
        def callback():
            pass
        n1 = add_callback(obj, callback)
        self.assertTrue(has_callback(obj, n1))
        n2 = add_callback(obj, callback)
        self.assertTrue(has_callback(obj, n2))
        remove_callback(obj, n2)
        self.assertFalse(has_callback(obj, n2))
        remove_callback(obj, n1)
        self.assertFalse(has_callback(obj, n1))

    def test_clear_callbacks(self):
        obj = Object()
        def callback():
            pass
        for i in range(10):
            add_callback(obj, callback)
        self.assertEqual(len(obj._callbacks), 10)
        clear_callbacks(obj)
        self.assertIsNone(obj._callbacks)

    def test_run_one(self):
        obj = Object()
        cbargs = []
        def callback(*args):
            cbargs.append(args)
        add_callback(obj, callback, (obj,))
        run_callbacks(obj)
        self.assertEqual(cbargs, [(obj,)])
        self.assertIsNone(obj._callbacks)

    def test_run_multiple(self):
        obj = Object()
        cbargs = []
        def callback(*args):
            cbargs.append(args)
        for i in range(5):
            add_callback(obj, callback, (obj,))
        run_callbacks(obj)
        self.assertEqual(cbargs, [(obj,)]*5)

    def test_walk_one(self):
        obj = Object()
        walk = []
        result = True
        def callback():
            pass
        add_callback(obj, callback, ('foo',))
        def walker(callback, args):
            walk.append((callback, args))
            return result
        walk_callbacks(obj, walker)
        self.assertEqual(walk, [(callback, ('foo',))])
        self.assertIsInstance(obj._callbacks, Node)
        result = False
        walk_callbacks(obj, walker)
        self.assertEqual(walk, [(callback, ('foo',))]*2)
        self.assertIsNone(obj._callbacks)

    def test_walk_multiple(self):
        obj = Object()
        def callback():
            pass
        ref = [(callback, i) for i in range(5)]
        for r in ref:
            add_callback(obj, r[0], r[1])
        walk = []
        result = True
        def walker(callback, args):
            walk.append((callback, args))
            return result
        walk_callbacks(obj, walker)
        self.assertEqual(walk, ref)
        self.assertEqual(len(obj._callbacks), 5)
        walk = []
        result = False
        walk_callbacks(obj, walker)
        self.assertEqual(walk, ref)
        self.assertFalse(obj._callbacks)


if __name__ == '__main__':
    unittest.main()
