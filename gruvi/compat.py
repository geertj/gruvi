#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys

# Some compatibility stuff that is not in six.

if sys.version_info[:2] == (2, 6):

    memoryview = buffer   # read-only but close enough for us
    bytes_types = (bytes, bytearray, buffer)

else:

    memoryview = memoryview
    bytes_types = (bytes, bytearray, memoryview)
