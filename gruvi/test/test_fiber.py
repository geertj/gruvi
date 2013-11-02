#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
import gruvi
from gruvi.test import UnitTest


class TestFiber(UnitTest):

    def test_run_fibers(self):
        hub = gruvi.Hub.get()
        counter = [0]
        def worker():
            counter[0] += 1
        for i in range(10000):
            gr = gruvi.Fiber(worker)
            gr.start()
        hub.switch()
        assert counter[0] == 10000

    def test_pass_args(self):
        hub = gruvi.Hub.get()
        result = []
        def target1(*args):
            result.extend(args)
            hub.switch_back()(1, 2)
            args = hub.switch()
            result.extend(args)
        def target2(*args):
            result.extend(args)
            hub.switch_back()(3, 4)
            args = hub.switch()
            result.extend(args)
        gr1 = gruvi.Fiber(target1, args=('a', 'b'))
        gr2 = gruvi.Fiber(target2, args=('c', 'd'))
        gr1.start()
        gr2.start()
        hub.switch()
        assert result == ['a', 'b', 'c', 'd', 1, 2, 3, 4]

    def test_log_exception(self):
        hub = gruvi.Hub.get()
        def target():
            raise ValueError
        gr1 = gruvi.Fiber(target)
        gr1.start()
        hub.switch()
