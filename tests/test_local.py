#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import gc
import unittest

import gruvi
from support import UnitTest


class TestLocal(UnitTest):

    def test_basic(self):
        local = gruvi.local()
        local.foo = 'bar'
        self.assertEqual(local.foo, 'bar')
        del local.foo
        self.assertRaises(AttributeError, local.__getattr__, 'foo')
        self.assertRaises(AttributeError, local.__delattr__, 'foo')

    def test_isolation(self):
        local = gruvi.local()
        interleaved = []
        def fiber1():
            local.foo = 10
            interleaved.append(1)
            gruvi.sleep(0)
            self.assertEqual(local.foo, 10)
            local.foo = 30
            interleaved.append(1)
            gruvi.sleep(0)
            self.assertEqual(local.foo, 30)
        def fiber2():
            self.assertFalse(hasattr(local, 'foo'))
            local.foo = 20
            interleaved.append(2)
            gruvi.sleep(0)
            self.assertEqual(local.foo, 20)
            local.foo = 40
            interleaved.append(2)
            gruvi.sleep(0)
            self.assertEqual(local.foo, 40)
        f1 = gruvi.spawn(fiber1)
        f2 = gruvi.spawn(fiber2)
        f1.join(); f2.join()
        self.assertFalse(hasattr(local, 'foo'))
        self.assertEqual(interleaved, [1, 2, 1, 2])

    def test_cleanup_on_fiber_exit(self):
        local = gruvi.local()
        def fiber1():
            local.foo = 10
        f1 = gruvi.spawn(fiber1)
        f1.join()
        # Access the local object as if access was from f1
        self.assertIn('foo', local._keys[f1])
        self.assertEqual(local._keys[f1]['foo'], 10)
        del f1; gc.collect()
        self.assertEqual(len(local._keys), 0)


if __name__ == '__main__':
    unittest.main()
