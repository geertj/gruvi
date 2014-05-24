#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import time

from gruvi.fibers import *
from support import *


def dummy_main():
    pass

def switch_parent(parent):
    while True:
        parent.switch()


class PerfFiber(PerformanceTest):

    def xperf_spawn_throughput(self):
        t0 = t1 = time.time()
        fibers = []
        while t1 - t0 < 0.2:
            fiber = Fiber(dummy_main)
            fiber._hub = current_fiber()
            fiber.switch()
            fibers.append(fiber)
            t1 = time.time()
        speed = len(fibers) / (t1 - t0)
        self.add_result(speed)

    def perf_switch_throughput(self):
        t0 = t1 = time.time()
        count = 0
        fiber = Fiber(switch_parent, args=(current_fiber(),))
        fiber._hub = current_fiber()
        while t1 - t0 < 0.2:
            fiber.switch()
            count += 1
            t1 = time.time()
        speed = count / (t1 - t0)
        self.add_result(speed)


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
