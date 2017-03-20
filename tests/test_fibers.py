#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import unittest

import gruvi
from support import UnitTest


class TestFiber(UnitTest):

    def test_basic(self):
        # Spawn fibers and join them.
        counter = [0]
        def worker():
            counter[0] += 1
            gruvi.sleep(0.1)
        fibers = []
        for i in range(1000):
            fibers.append(gruvi.spawn(worker))
        for fiber in fibers:
            self.assertTrue(fiber.alive)
        for fiber in fibers:
            fiber.join()
        self.assertEqual(counter[0], 1000)
        for fiber in fibers:
            self.assertFalse(fiber.alive)

    def test_spawn_nested(self):
        # Spawn fibers from fiber.
        joined = []
        def spawn_fiber(i):
            if i == 0:
                return
            fiber = gruvi.spawn(spawn_fiber, i-1)
            fiber.join()
            joined.append(i-1)
        fiber = gruvi.spawn(spawn_fiber, 1000)
        fiber.join()
        self.assertEqual(joined, list(range(1000)))

    def test_switch_hub_only(self):
        # Ensure that only the hub may switch to or throw into a fiber.
        ready = []
        exceptions = []
        def worker():
            ready.append(gruvi.current_fiber())
            try:
                gruvi.sleep(0.1)
            except Exception as e:
                exceptions.append(e)
        fiber = gruvi.Fiber(worker)
        self.assertRaises(RuntimeError, fiber.switch)
        self.assertRaises(RuntimeError, fiber.throw, None)
        hub = gruvi.get_hub()
        hub.run_callback(fiber.switch)
        gruvi.sleep(0)
        self.assertEqual(ready, [fiber])
        error = RuntimeError('foo')
        hub.run_callback(fiber.throw, RuntimeError, error)
        gruvi.sleep(0)
        self.assertEqual(exceptions, [error])

    def test_cancel(self):
        # Ensure that it's possible to cancel() a fiber.
        def sleeper():
            gruvi.sleep(1000)
        fiber = gruvi.spawn(sleeper)
        gruvi.sleep(0)
        self.assertTrue(fiber.alive)
        fiber.cancel()
        gruvi.sleep(0)
        self.assertFalse(fiber.alive)


if __name__ == '__main__':
    unittest.main()
