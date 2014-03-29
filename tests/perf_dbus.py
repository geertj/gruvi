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
from tests.support import *
from tests.test_dbus import set_buffer


class PerfDBus(PerformanceTest):

    def perf_dbus_parsing_speed(self):
        m = b'l\1\0\1\x64\0\0\0\1\0\0\0\0\0\0\0' + (b'x'*100)
        buf = m * 100
        ctx = dbus_ffi.ffi.new('struct context *')
        nbytes = 0
        t0 = t1 = time.time()
        while t1 - t0 < 1:
            set_buffer(ctx, buf)
            while ctx.offset != len(buf):
                error = dbus_ffi.lib.split(ctx)
                self.assertEqual(error, 0)
                self.assertEqual(ctx.error, error)
                self.assertEqual(ctx.offset % len(m), 0)
            nbytes += len(buf)
            t1 = time.time()
        speed = nbytes / (1024 * 1024) / (t1 - t0)
        self.add_result(speed)


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
