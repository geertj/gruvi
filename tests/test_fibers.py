#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import gruvi
from support import UnitTest, unittest


class TestFiber(UnitTest):

    def test_spawn(self):
        counter = [0]
        def worker():
            counter[0] += 1
        fibers = []
        for i in range(1000):
            fibers.append(gruvi.spawn(worker))
        for fiber in fibers:
            fiber.join()
        self.assertEqual(counter[0], 1000)

    def test_join(self):
        joined = []
        def spawn_fibers(i):
            if i == 0:
                return
            fiber = gruvi.spawn(spawn_fibers, i-1)
            fiber.join()
            joined.append(i-1)
        fiber = gruvi.spawn(spawn_fibers, 1000)
        fiber.join()
        self.assertEqual(joined, list(range(1000)))

    def test_pass_args(self):
        hub = gruvi.get_hub()
        result = []
        def target1(*args):
            result.append(args)
            gruvi.switch_back()(1, 2, foo='bar')
            result.extend(hub.switch())
        def target2(*args):
            result.append(args)
            gruvi.switch_back()(3, 4, baz='qux')
            result.extend(hub.switch())
        f1 = gruvi.spawn(target1, 'a', 'b')
        f2 = gruvi.spawn(target2, 'c', 'd')
        f1.join(); f2.join()
        self.assertEqual(result, [('a', 'b'), ('c', 'd'), (1, 2), {'foo': 'bar'},
                                  (3, 4), {'baz': 'qux'}])


if __name__ == '__main__':
    unittest.main()
