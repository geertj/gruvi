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
import gruvi.test
from gruvi import util

import mock
import greenlet


class TestLocal(gruvi.test.UnitTest):

    def test_isolation(self):
        local = gruvi.local()
        def greenlet1():
            local.foo = 10
            util.sleep(0)
            assert local.foo == 10
            local.foo = 30
            util.sleep(0)
            assert local.foo == 30
        def greenlet2():
            assert not hasattr(local, 'foo')
            local.foo = 20
            util.sleep(0)
            assert local.foo == 20
            local.foo = 40
            util.sleep(0)
            assert local.foo == 40
        hub = gruvi.Hub.get()
        gr1 = gruvi.Greenlet(hub)
        gr2 = gruvi.Greenlet(hub)
        gr1.start(greenlet1)
        gr2.start(greenlet2)
        hub.switch()
        assert not hasattr(local, 'foo')

    def test_cleanup_on_greenlet_exit(self):
        local = gruvi.local()
        def greenlet1():
            local.foo = 10
        hub = gruvi.Hub.get()
        gr1 = gruvi.Greenlet(hub)
        gr1.start(greenlet1)
        hub.switch()
        grid = id(gr1)
        with mock.patch('__builtin__.id', lambda obj: grid):
            assert hasattr(local, 'foo')
            assert local.foo == 10
        del gr1
        # Is the following enough to have PyPy/Jython/IronPython finalize
        # `gr1` and call its weakref callbacks?
        gc.collect()
        with mock.patch('__builtin__.id', lambda obj: grid):
            assert not hasattr(local, 'foo')
