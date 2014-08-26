#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import six
import unittest

from gruvi.sslcompat import MemoryBIO
from support import UnitTest


class MemoryBIOTests(UnitTest):

    def test_read_write(self):
        bio = MemoryBIO()
        bio.write(b'foo')
        self.assertEqual(bio.read(), b'foo')
        self.assertEqual(bio.read(), b'')
        bio.write(b'foo')
        bio.write(b'bar')
        self.assertEqual(bio.read(), b'foobar')
        self.assertEqual(bio.read(), b'')
        bio.write(b'baz')
        self.assertEqual(bio.read(2), b'ba')
        self.assertEqual(bio.read(1), b'z')
        self.assertEqual(bio.read(1), b'')

    def test_eof(self):
        bio = MemoryBIO()
        self.assertFalse(bio.eof)
        self.assertEqual(bio.read(), b'')
        self.assertFalse(bio.eof)
        bio.write(b'foo')
        self.assertFalse(bio.eof)
        bio.write_eof()
        self.assertFalse(bio.eof)
        self.assertEqual(bio.read(2), b'fo')
        self.assertFalse(bio.eof)
        self.assertEqual(bio.read(1), b'o')
        self.assertTrue(bio.eof)
        self.assertEqual(bio.read(), b'')
        self.assertTrue(bio.eof)

    def test_pending(self):
        bio = MemoryBIO()
        self.assertEqual(bio.pending, 0)
        bio.write(b'foo')
        self.assertEqual(bio.pending, 3)
        for i in range(3):
            bio.read(1)
            self.assertEqual(bio.pending, 3-i-1)
        for i in range(3):
            bio.write(b'x')
            self.assertEqual(bio.pending, i+1)
        bio.read()
        self.assertEqual(bio.pending, 0)

    def test_buffer_types(self):
        bio = MemoryBIO()
        bio.write(b'foo')
        self.assertEqual(bio.read(), b'foo')
        bio.write(bytearray(b'bar'))
        self.assertEqual(bio.read(), b'bar')
        bio.write(memoryview(b'baz'))
        self.assertEqual(bio.read(), b'baz')

    def test_error_types(self):
        bio = MemoryBIO()
        if six.PY3:
            self.assertRaises(TypeError, bio.write, 'foo')
        self.assertRaises(TypeError, bio.write, None)
        self.assertRaises(TypeError, bio.write, True)
        self.assertRaises(TypeError, bio.write, 1)


if __name__ == '__main__':
    unittest.main()
