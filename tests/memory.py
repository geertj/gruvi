#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import unittest

import gruvi
from gruvi.logging import get_logger
from gruvi import callbacks
from support import MemoryTest, sizeof


class TestMemory(MemoryTest):

    def mem_fiber(self):
        self.add_result(sizeof(gruvi.Fiber(lambda: None), exclude=('_log', '_hub', '_thread')))

    def mem_switch_back(self):
        self.add_result(sizeof(gruvi.switch_back(), exclude=('_hub', '_fiber')))

    def mem_assert_no_switchpoints(self):
        self.add_result(sizeof(gruvi.assert_no_switchpoints(), exclude=('_hub',)))

    def mem_hub(self):
        self.add_result(sizeof(gruvi.Hub(), exclude=('_log', '_thread', '_poll')))

    def mem_lock(self):
        self.add_result(sizeof(gruvi.Lock()))

    def mem_rlock(self):
        self.add_result(sizeof(gruvi.RLock()))

    def mem_event(self):
        self.add_result(sizeof(gruvi.Event()))

    def mem_condition(self):
        self.add_result(sizeof(gruvi.Condition()))

    def mem_queue(self):
        # In a Queue there's 2 conditions that share the same lock.
        queue = gruvi.Queue()
        self.add_result(sizeof(queue, exclude=('_lock',)) + sizeof(queue._lock))

    def mem_lifoqueue(self):
        self.add_result(sizeof(gruvi.LifoQueue(), exclude=('_lock',)) + sizeof(gruvi.Lock()))

    def mem_priorityqueue(self):
        self.add_result(sizeof(gruvi.PriorityQueue(), exclude=('_lock',)) + sizeof(gruvi.Lock()))

    def mem_logger(self):
        self.add_result(sizeof(get_logger(), exclude=('logger',)))

    def mem_dllist(self):
        self.add_result(sizeof(callbacks.dllist()))

    def mem_dllist_node(self):
        self.add_result(sizeof(callbacks.Node()))


if __name__ == '__main__':
    TestMemory.setup_loader()
    unittest.main()
