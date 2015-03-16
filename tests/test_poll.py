#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import unittest

from gruvi import get_hub, Event
from gruvi.poll import MultiPoll, Poller, READABLE, WRITABLE
from gruvi.poll import check as check_mpoll

from support import UnitTest, socketpair


class TestMultiPoll(UnitTest):

    def test_basic(self):
        s1, s2 = socketpair()
        fd = s2.fileno()
        mp = MultiPoll(get_hub().loop, fd)
        check_mpoll(mp)
        cbargs = []
        called = Event()
        def callback(fd, events):
            cbargs.append((fd, events))
            called.set()
        mp.add_callback(READABLE, callback)
        check_mpoll(mp)
        called.wait(0.01)
        self.assertEqual(cbargs, [])
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE)])
        self.assertEqual(s2.recv(10), b'x')
        del cbargs[:]; called.clear()
        called.wait(0.01)
        self.assertEqual(cbargs, [])
        mp.close()
        check_mpoll(mp)
        s1.close(); s2.close()

    def test_multiple(self):
        s1, s2 = socketpair()
        fd = s2.fileno()
        mp = MultiPoll(get_hub().loop, fd)
        cbargs = []
        called = Event()
        def callback(arg=0):
            def _callback(fd, events):
                cbargs.append((fd, events, arg))
                called.set()
            return _callback
        mp.add_callback(READABLE, callback(0))
        check_mpoll(mp)
        mp.add_callback(READABLE, callback(1))
        check_mpoll(mp)
        mp.add_callback(WRITABLE, callback(2))
        check_mpoll(mp)
        mp.add_callback(WRITABLE, callback(3))
        check_mpoll(mp)
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, WRITABLE, 2), (fd, WRITABLE, 3)])
        del cbargs[:]; called.clear()
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE, 0), (fd, READABLE, 1),
                                  (fd, WRITABLE, 2), (fd, WRITABLE, 3)])
        self.assertEqual(s2.recv(10), b'x')
        mp.close()
        check_mpoll(mp)
        s1.close(); s2.close()

    def test_remove(self):
        s1, s2 = socketpair()
        fd = s2.fileno()
        mp = MultiPoll(get_hub().loop, fd)
        cbargs = []
        called = Event()
        def callback(arg=0):
            def _callback(fd, events):
                cbargs.append((fd, events, arg))
                called.set()
            return _callback
        h1 = mp.add_callback(READABLE, callback(0))
        check_mpoll(mp)
        h2 = mp.add_callback(READABLE, callback(1))
        check_mpoll(mp)
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE, 0), (fd, READABLE, 1)])
        del cbargs[:]; called.clear()
        mp.remove_callback(h1)
        check_mpoll(mp)
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE, 1)])
        mp.remove_callback(h2)
        check_mpoll(mp)
        mp.close()
        check_mpoll(mp)
        s1.close(); s2.close()

    def test_update(self):
        s1, s2 = socketpair()
        fd = s2.fileno()
        mp = MultiPoll(get_hub().loop, fd)
        cbargs = []
        called = Event()
        def callback(fd, events):
            cbargs.append((fd, events))
            called.set()
        h1 = mp.add_callback(READABLE, callback)
        check_mpoll(mp)
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE)])
        del cbargs[:]; called.clear()
        mp.update_callback(h1, READABLE|WRITABLE)
        check_mpoll(mp)
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE|WRITABLE)])
        del cbargs[:]; called.clear()
        mp.update_callback(h1, WRITABLE)
        check_mpoll(mp)
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, WRITABLE)])
        del cbargs[:]; called.clear()
        mp.update_callback(h1, 0)
        check_mpoll(mp)
        s1.send(b'x')
        called.wait(0.01)
        self.assertEqual(cbargs, [])
        mp.close()
        check_mpoll(mp)
        s1.close(); s2.close()

    def test_close(self):
        s1, s2 = socketpair()
        fd = s2.fileno()
        mp = MultiPoll(get_hub().loop, fd)
        cbargs = []
        called = Event()
        def callback(fd, events):
            cbargs.append((fd, events))
            called.set()
        h1 = mp.add_callback(READABLE, callback)
        h2 = mp.add_callback(READABLE, callback)
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE), (fd, READABLE)])
        del cbargs[:]; called.clear()
        mp.close()
        called.wait(0.01)
        self.assertEqual(cbargs, [])
        self.assertRaises(RuntimeError, mp.add_callback, READABLE, callback)
        self.assertRaises(RuntimeError, mp.remove_callback, h1)
        self.assertRaises(RuntimeError, mp.remove_callback, h2)
        self.assertRaises(RuntimeError, mp.update_callback, h1, WRITABLE)
        self.assertRaises(RuntimeError, mp.update_callback, h2, WRITABLE)
        s1.close(); s2.close()


class TestPoller(UnitTest):

    def test_add_remove(self):
        poll = Poller(get_hub().loop)
        cbargs = []
        called = Event()
        def callback(fd, events):
            cbargs.append((fd, events))
            called.set()
        s1, s2 = socketpair()
        fd = s2.fileno()
        handle = poll.add_callback(fd, READABLE, callback)
        self.assertIsNotNone(handle)
        called.wait(0.01)
        self.assertEqual(cbargs, [])
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE)])
        del cbargs[:]; called.clear()
        poll.remove_callback(fd, handle)
        called.wait(0.01)
        self.assertEqual(cbargs, [])
        poll.close()
        s1.close(); s2.close()

    def test_update(self):
        poll = Poller(get_hub().loop)
        cbargs = []
        called = Event()
        def callback(fd, events):
            cbargs.append((fd, events))
            called.set()
        s1, s2 = socketpair()
        fd = s2.fileno()
        handle = poll.add_callback(fd, WRITABLE, callback)
        self.assertIsNotNone(handle)
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, WRITABLE)])
        del cbargs[:]; called.clear()
        poll.update_callback(fd, handle, READABLE|WRITABLE)
        s1.send(b'x')
        called.wait(0.1)
        self.assertEqual(cbargs, [(fd, READABLE|WRITABLE)])
        del cbargs[:]; called.clear()
        poll.close()
        s1.close(); s2.close()

    def test_close(self):
        poll = Poller(get_hub().loop)
        cbargs = []
        called = Event()
        def callback(fd, events):
            cbargs.append((fd, events))
            called.set()
        s1, s2 = socketpair()
        fd = s2.fileno()
        handle = poll.add_callback(fd, READABLE, callback)
        self.assertIsNotNone(handle)
        s1.send(b'x')
        poll.close()
        called.wait(0.01)
        self.assertEqual(cbargs, [])
        self.assertRaises(RuntimeError, poll.add_callback, fd, READABLE, callback)
        self.assertRaises(RuntimeError, poll.remove_callback, fd, handle)
        self.assertRaises(RuntimeError, poll.update_callback, fd, handle, WRITABLE)
        s1.close(); s2.close()

    def test_multiple_fds(self):
        poll = Poller(get_hub().loop)
        cbargs = []
        called = Event()
        def callback(fd, events):
            cbargs.append((fd, events))
            called.set()
        s11, s12 = socketpair()
        fd1 = s12.fileno()
        poll.add_callback(fd1, READABLE, callback)
        s21, s22 = socketpair()
        fd2 = s22.fileno()
        poll.add_callback(fd2, READABLE, callback)
        s11.send(b'x')
        s21.send(b'x')
        called.wait()
        self.assertEqual(cbargs, [(fd1, READABLE), (fd2, READABLE)])
        poll.close()
        s11.close(); s12.close()
        s21.close(); s22.close()


if __name__ == '__main__':
    unittest.main()
