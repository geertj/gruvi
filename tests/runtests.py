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
parser.add_argument('suite', nargs=1, help='the test suite to run')
args = parser.parse_args()

suite = args.suite[0]
if suite not in ('unit', 'performance'):
    sys.stderr.write('Error: unkown suite {0!r}\n'.format(suite))
    sys.stderr.write('Available suites are "unit" and "performance".\n')
    sys.exit(1)

testdir = os.path.split(os.path.abspath(__file__))[0]
os.chdir(testdir)
parent, _ = os.path.split(testdir)
sys.path.insert(0, parent)

if suite == 'unit':
    pattern = 'test_*.py'
    TestLoader.testMethodPrefix = 'test'
elif suite == 'performance':
    pattern = 'perf_*.py'
    TestLoader.testMethodPrefix = 'perf'
    try: os.unlink('performance.txt')
    except OSError: pass

loader = TestLoader()
tests = loader.discover('.', pattern)

runner = TextTestRunner(verbosity=1, buffer=True)
runner.run(tests)
