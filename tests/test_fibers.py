#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import gruvi
from support import *


class TestFiber(UnitTest):

    def test_run_fibers(self):
        hub = gruvi.get_hub()
        counter = [0]
        done = gruvi.Signal()
        def worker():
            counter[0] += 1
            if counter[0] == 1000:
                done.emit()
        for i in range(1000):
            gr = gruvi.Fiber(worker)
            gr.start()
        done.wait()
        self.assertEqual(counter[0], 1000)

    def test_pass_args(self):
        hub = gruvi.get_hub()
        result = []
        def target1(*args):
            result.extend(args)
            gruvi.switch_back()(1, 2)
            args, kwargs = hub.switch()
            result.extend(args)
            return True
        def target2(*args):
            result.extend(args)
            gruvi.switch_back()(3, 4)
            args, kwargs = hub.switch()
            result.extend(args)
            return True
        gr1 = gruvi.Fiber(target1, args=('a', 'b'))
        gr1.start()
        gr2 = gruvi.Fiber(target2, args=('c', 'd'))
        gr2.start()
        for siginfo in gruvi.waitall([gr1.done, gr2.done]):
            self.assertIsInstance(siginfo[0], gruvi.Signal)
            self.assertTrue(siginfo[1])
        self.assertEqual(result, ['a', 'b', 'c', 'd', 1, 2, 3, 4])

    def test_log_exception(self):
        hub = gruvi.get_hub()
        def target():
            raise ValueError
        gr1 = gruvi.Fiber(target)
        gr1.start()
        gruvi.sleep(0)


if __name__ == '__main__':
    unittest.main(buffer=True)
