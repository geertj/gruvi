#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import time
import unittest

import gruvi
from gruvi.fibers import Fiber
from support import PerformanceTest


class PerfFiber(PerformanceTest):

    def perf_spawn_throughput(self):
        # Measure the number of fibers we can spawn per second.
        t0 = t1 = time.time()
        count = [0]
        def dummy_fiber():
            count[0] += 1
        while t1 - t0 < 0.2:
            fiber = Fiber(dummy_fiber)
            fiber.start()
            gruvi.sleep(0)
            t1 = time.time()
        speed = count[0] / (t1 - t0)
        self.add_result(speed)

    def perf_switch_throughput(self):
        # Measure the number of switches we can do per second.
        t0 = t1 = time.time()
        count = [0]
        def switch_parent():
            while True:
                gruvi.sleep(0)
        fiber = Fiber(switch_parent)
        fiber.start()
        while t1 - t0 < 0.2:
            gruvi.sleep(0)
            count[0] += 1
            t1 = time.time()
        speed = count[0] / (t1 - t0)
        self.add_result(speed)
        fiber.cancel()
        gruvi.sleep(0)


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
