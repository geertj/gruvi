# # This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import random
import unittest

from gruvi.callbacks import dllist, Node
from gruvi.callbacks import check as check_dllist
from gruvi.callbacks import add_callback, remove_callback, pop_callback
from gruvi.callbacks import walk_callbacks, run_callbacks
from gruvi.callbacks import has_callback, clear_callbacks
from support import UnitTest


def get_callbacks(obj):
    callbacks = []
    while True:
        callback = pop_callback(obj)
        if not callback:
            return
        callbacks.append(callback)
    return callbacks


class TestDllist(UnitTest):

    def test_basic(self):
        dll = dllist()
        check_dllist(dll)
        self.assertIsNone(dll.first)
        self.assertIsNone(dll.last)
        self.assertEqual(len(dll), 0)
        # insert first element
        n1 = Node('foo')
        dll.insert(n1)
        self.assertIs(dll.first, n1)
        self.assertIs(dll.last, n1)
        self.assertEqual(len(dll), 1)
        self.assertIn(n1, dll)
        check_dllist(dll)
        # insert second at end
        n2 = Node('bar')
        dll.insert(n2)
        self.assertIs(dll.first, n1)
        self.assertIs(dll.last, n2)
        self.assertEqual(len(dll), 2)
        self.assertIn(n2, dll)
        check_dllist(dll)
        # insert in middle
        n3 = Node('baz')
        dll.insert(n3, before=n2)
        self.assertIs(dll.first, n1)
        self.assertIs(dll.last, n2)
        self.assertEqual(len(dll), 3)
        self.assertIn(n3, dll)
        check_dllist(dll)
        # remove middle
        dll.remove(n3)
        self.assertIs(dll.first, n1)
        self.assertIs(dll.last, n2)
        self.assertEqual(len(dll), 2)
        self.assertNotIn(n3, dll)
        check_dllist(dll)
        # remove first
        dll.remove(n1)
        self.assertIs(dll.first, n2)
        self.assertIs(dll.last, n2)
        self.assertEqual(len(dll), 1)
        self.assertNotIn(n1, dll)
        check_dllist(dll)
        # remove remaining element
        dll.remove(n2)
        self.assertIsNone(dll.first)
        self.assertIsNone(dll.last)
        self.assertEqual(len(dll), 0)
        self.assertNotIn(n2, dll)
        check_dllist(dll)

    def test_iter(self):
        dll = dllist()
        for i in range(10):
            dll.insert(Node(10+i))
            check_dllist(dll)
        value = 10
        for node in dll:
            self.assertIsInstance(node, Node)
            self.assertEqual(node.callback, value)
            value += 1
        check_dllist(dll)

    def test_args(self):
        dll = dllist()
        def callback():
            pass
        n1 = Node(callback)
        self.assertEqual(n1.callback, callback)
        self.assertIsNone(n1.args)
        dll.insert(n1)
        n2 = Node(callback, 'foo')
        self.assertIs(n2.callback, callback)
        self.assertEqual(n2.args, 'foo')
        dll.insert(n2)
        nodes = list(dll)
        self.assertEqual(nodes[0].callback, callback)
        self.assertIsNone(nodes[0].args)
        self.assertEqual(nodes[1].callback, callback)
        self.assertEqual(nodes[1].args, 'foo')

    def test_clear(self):
        dll = dllist()
        for i in range(10):
            dll.insert(Node(i))
        self.assertEqual(len(dll), 10)
        dll.clear()
        self.assertEqual(len(dll), 0)

    def test_many_nodes(self):
        nodes = []
        dll = dllist()
        count = 10000
        for i in range(count):
            before = random.choice(nodes) if nodes else None
            node = Node(i)
            dll.insert(node, before)
            nodes.append(node)
            self.assertEqual(len(dll), i+1)
            if i % 100 == 0:
                check_dllist(dll)
        check_dllist(dll)
        for i in range(count):
            r = random.randint(0, len(nodes)-1)
            node = nodes[r]; del nodes[r]
            dll.remove(node)
            self.assertEqual(len(dll), count-i-1)
            if i % 100 == 0:
                check_dllist(dll)
        check_dllist(dll)


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
        self.assertIs(obj._callbacks.callback, callback)
        self.assertEqual(obj._callbacks.args, ())
        self.assertEqual(pop_callback(obj), (callback, ()))
        self.assertEqual(obj._callbacks, None)
        add_callback(obj, callback, (1, 2))
        self.assertIsInstance(obj._callbacks, Node)
        self.assertIs(obj._callbacks.callback, callback)
        self.assertEqual(obj._callbacks.args, (1, 2))
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
