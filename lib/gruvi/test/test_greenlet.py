#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import print_function

import pyuv
import gruvi
import gruvi.util


class TestGreenlet(object):

    def test_run_greenlets(self):
        hub = gruvi.Hub.get()
        counter = [0]
        def worker():
            counter[0] += 1
        for i in range(1000):
            gr = gruvi.Greenlet(hub)
            gr.start(worker)
        hub.switch()
        assert counter[0] == 1000
