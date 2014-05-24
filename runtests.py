#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys

from argparse import ArgumentParser

if sys.version_info[:2] >= (2,7):
    from unittest import TestLoader, TextTestRunner
else:
    from unittest2 import TestLoader, TextTestRunner


parser = ArgumentParser()
parser.add_argument('suite', help='the test suite to run',
                     choices=('unit', 'performance', 'memory', 'documentation'))
args = parser.parse_args()
suite = args.suite

# Change directory to tests/ irrespective of where we're called from.
topdir = os.path.split(os.path.abspath(__file__))[0]
testdir = os.path.join(topdir, 'tests')
os.chdir(testdir)

# If running under tox, replace the entry for the current directory on sys.path
# with the test directory. This prevents the tox runs from running in the
# potentially unclean environment from the checkout our source tree.
# Otherwise, if not running under tox, we want the option to run from the
# current directory, so we add the test directory instead.
if os.environ.get('TOX') == 'yes':
    sys.path[0] = testdir
else:
    sys.path.insert(0, testdir)

from support import *

if suite == 'unit':
    pattern = 'test_*.py'
elif suite == 'performance':
    pattern = 'perf_*.py'
    PerformanceTest.setup_loader()
    PerformanceTest.start_new_results()
elif suite == 'memory':
    pattern = 'memory.py'
    MemoryTest.setup_loader()
    MemoryTest.start_new_results()
elif suite == 'documentation':
    pattern = 'documentation.py'

loader = TestLoader()
tests = loader.discover('.', pattern)

runner = TextTestRunner(verbosity=1, buffer=False)
result = runner.run(tests)
if result.errors or result.failures:
    sys.exit(1)
