#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function, division

import time

from gruvi.http import HttpProtocol
from support import PerformanceTest, unittest, MockTransport


class PerfHttp(PerformanceTest):

    def perf_parsing_speed(self):
        transport = MockTransport()
        protocol = HttpProtocol(False)
        transport.start(protocol)
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 10000\r\n\r\n'
        r += b'x' * 10000
        reqs = 4 * r
        nbytes = 0
        t0 = t1 = time.time()
        while t1 - t0 < 1:
            protocol.data_received(reqs)
            protocol._queue.clear()
            nbytes += len(reqs)
            t1 = time.time()
        speed = nbytes / (t1 - t0) / (1024 * 1024)
        self.add_result(speed)


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
