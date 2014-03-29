#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function, division

import time

from gruvi import dbus_ffi
from gruvi.http import HttpParser
from tests.support import *
from tests.test_dbus import set_buffer


class PerfHttp(PerformanceTest):

    def perf_http_parsing_speed(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n'
        r += b'x' * 1000
        reqs = 10 * r
        parser = HttpParser()
        nbytes = 0
        t0 = t1 = time.time()
        while t1 - t0 < 1:
            nparsed = parser.feed(reqs)
            self.assertEqual(nparsed, len(reqs))
            nmessages = 0
            while True:
                msg = parser.pop_message()
                if msg is None:
                    break
                nmessages += 1
            self.assertEqual(nmessages, 10)
            nbytes += nparsed
            t1 = time.time()
        speed = nbytes / (1024 * 1024) / (t1 - t0)
        self.add_result(speed)


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
