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

from gruvi.callbacks import dllist, Node
from support import PerformanceTest


class PerfDllist(PerformanceTest):

    def perf_insert_throughput(self):
        # Measure the number inserts we can do per second
        t0 = t1 = time.time()
        count = 0
        batch = 1000
        dll = dllist()
        value = 'foo'
        while t1 - t0 < 0.2:
            for i in range(batch):
                dll.insert(Node(value))
            count += batch
            t1 = time.time()
        speed = count / (t1 - t0)
        self.add_result(speed)

if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
