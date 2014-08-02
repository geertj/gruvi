#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import unittest
from gruvi.socketpair import socketpair
from support import UnitTest


class TestSocketpair(UnitTest):

    def test_basic(self):
        s1, s2 = socketpair()
        s1.send(b'foo')
        self.assertEqual(s2.recv(3), b'foo')
        s2.send(b'bar')
        self.assertEqual(s1.recv(3), b'bar')
        s1.close(); s2.close()


if __name__ == '__main__':
    unittest.main()
