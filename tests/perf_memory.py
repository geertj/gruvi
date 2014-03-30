#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from gruvi.sync import *
from gruvi.logging import get_logger
from tests.support import *


class PerfMemory(PerformanceTest):

    def perf_lock_size(self):
        self.add_result(sizeof(Lock()))

    def perf_signal_size(self):
        self.add_result(sizeof(Signal(), exclude=('_log',)))

    def perf_queue_size(self):
        self.add_result(sizeof(Queue(), exclude=('_log',)))

    def perf_logger_size(self):
        self.add_result(sizeof(get_logger(), exclude=('logger',)))


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
