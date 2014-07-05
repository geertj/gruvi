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
    from unittest import TestLoader, TextTestRunner, TestSuite
else:
    from unittest2 import TestLoader, TextTestRunner, TestSuite


parser = ArgumentParser()
parser.add_argument('-v', '--verbose', help='be more verbose', action='store_true')
parser.add_argument('-f', '--failfast', help='stop on first failure', action='store_true')
parser.add_argument('-b', '--buffer', help='buffer stdout and stderr', action='store_true')
parser.add_argument('suite', nargs='+', help='name of test suite to run', metavar='suite',
                    choices=('unit', 'performance', 'memory', 'documentation', 'examples'))
args = parser.parse_args()

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

suite = TestSuite()

for name in args.suite:
    TestCase.setup_loader()
    if name == 'unit':
        pattern = 'test_*.py'
    elif name == 'performance':
        pattern = 'perf_*.py'
        PerformanceTest.setup_loader()
        PerformanceTest.start_new_results()
    elif name == 'memory':
        pattern = 'memory.py'
        MemoryTest.setup_loader()
        MemoryTest.start_new_results()
    elif name == 'documentation':
        pattern = 'documentation.py'
    elif name == 'examples':
        pattern = 'examples.py'
    loader = TestLoader()
    tests = loader.discover('.', pattern)
    suite.addTest(tests)

verbosity = 2 if args.verbose else 1
runner = TextTestRunner(verbosity=verbosity, buffer=args.buffer, failfast=args.failfast)
result = runner.run(suite)
if result.errors or result.failures:
    sys.exit(1)
