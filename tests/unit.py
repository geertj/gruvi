#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

import os
import sys

if sys.version_info[:2] < (3,2):
    sys.stderr.write('This driver requires Python >= 3.2\n')
    sys.stderr.write('Please use "nosetests" instead.\n')
    sys.exit(1)

from unittest import TestLoader, TextTestRunner

testdir = os.path.split(os.path.abspath(__file__))[0]
os.chdir(testdir)

loader = TestLoader()
tests = loader.discover('.', 'test_*.py')

runner = TextTestRunner(verbosity=1, buffer=True)
runner.run(tests)
