#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from support import UnitTest, unittest
from gruvi.compat import fixup_format_string


class TestReplaceFmt(UnitTest):

    def test_basic(self):
        self.assertEqual(fixup_format_string(''), '')
        self.assertEqual(fixup_format_string('{}'), '{0}')
        self.assertEqual(fixup_format_string('{} {}'), '{0} {1}')
        self.assertEqual(fixup_format_string('foo {} {}'), 'foo {0} {1}')

    def test_escaped(self):
        self.assertEqual(fixup_format_string('{{}}'), '{{}}')
        self.assertEqual(fixup_format_string('{{}}{{}}'), '{{}}{{}}')
        self.assertEqual(fixup_format_string('{{{}}}'), '{{{0}}}')
        self.assertEqual(fixup_format_string('{{{}}}{{{}}}'), '{{{0}}}{{{1}}}')

    def test_extended(self):
        self.assertEqual(fixup_format_string('{!s}'), '{0!s}')
        self.assertEqual(fixup_format_string('{:.2f}'), '{0:.2f}')


if __name__ == '__main__':
    unittest.main()
