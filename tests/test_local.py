#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import gc
import gruvi
from gruvi import util
from support import *


class TestLocal(UnitTest):

    def test_isolation(self):
        local = gruvi.local()
        interleaved = []
        def fiber1():
            local.foo = 10
            interleaved.append(1)
            util.sleep(0)
            self.assertEqual(local.foo, 10)
            local.foo = 30
            interleaved.append(1)
            util.sleep(0)
            self.assertEqual(local.foo, 30)
        def fiber2():
            self.assertFalse(hasattr(local, 'foo'))
            local.foo = 20
            interleaved.append(2)
            util.sleep(0)
            self.assertEqual(local.foo, 20)
            local.foo = 40
            interleaved.append(2)
            util.sleep(0)
            self.assertEqual(local.foo, 40)
        gr1 = gruvi.Fiber(fiber1)
        gr2 = gruvi.Fiber(fiber2)
        gr1.start()
        gr2.start()
        for siginfo in gruvi.waitall([gr1.done, gr2.done]):
            pass
        self.assertFalse(hasattr(local, 'foo'))
        self.assertEqual(interleaved, [1, 2, 1, 2])

    def test_cleanup_on_fiber_exit(self):
        hub = gruvi.get_hub()
        local = gruvi.local()
        def fiber1():
            local.foo = 10
        gr1 = gruvi.Fiber(fiber1)
        gr1.start()
        gr1.done.wait()
        # Access the local object as if access was from gr1
        self.assertIn('foo', local._keys[gr1])
        self.assertEqual(local._keys[gr1]['foo'], 10)
        # Is the following enough to have PyPy/Jython/IronPython finalize
        # `gr1` and call its weakref callbacks?
        del gr1
        gc.collect(); gc.collect(); gc.collect()
        self.assertEqual(len(local._keys), 0)


if __name__ == '__main__':
    unittest.main(buffer=True)
