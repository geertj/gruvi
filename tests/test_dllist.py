#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import random
import unittest

from gruvi.dllist import dllist, Node
from gruvi.dllist import check as check_dllist
from support import UnitTest


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
            self.assertEqual(node.data, value)
            value += 1
        check_dllist(dll)

    def test_extra(self):
        dll = dllist()
        data = object()
        n1 = Node(data)
        self.assertEqual(n1.data, data)
        self.assertIsNone(n1.extra)
        dll.insert(n1)
        n2 = Node(data, 'foo')
        self.assertIs(n2.data, data)
        self.assertEqual(n2.extra, 'foo')
        dll.insert(n2)
        nodes = list(dll)
        self.assertEqual(nodes[0].data, data)
        self.assertIsNone(nodes[0].extra)
        self.assertEqual(nodes[1].data, data)
        self.assertEqual(nodes[1].extra, 'foo')

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


if __name__ == '__main__':
    unittest.main()
