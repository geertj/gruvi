#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from support import *
from gruvi.logging import replace_fmt


class TestReplaceFmt(UnitTest):

    def test_basic(self):
        self.assertEqual(replace_fmt(''), '')
        self.assertEqual(replace_fmt('{}'), '{0}')
        self.assertEqual(replace_fmt('{} {}'), '{0} {1}')
        self.assertEqual(replace_fmt('foo {} {}'), 'foo {0} {1}')

    def test_escaped(self):
        self.assertEqual(replace_fmt('{{}}'), '{{}}')
        self.assertEqual(replace_fmt('{{}}{{}}'), '{{}}{{}}')
        self.assertEqual(replace_fmt('{{{}}}'), '{{{0}}}')
        self.assertEqual(replace_fmt('{{{}}}{{{}}}'), '{{{0}}}{{{1}}}')

    def test_extended(self):
        self.assertEqual(replace_fmt('{!s}'), '{0!s}')
        self.assertEqual(replace_fmt('{:.2f}'), '{0:.2f}')


if __name__ == '__main__':
    unittest.main()
