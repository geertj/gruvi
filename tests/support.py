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
import shutil
import tempfile
import logging
import subprocess
import functools

if sys.version_info[:2] >= (2,7):
    import unittest
else:
    import unittest2 as unittest

SkipTest = unittest.SkipTest

from gruvi.logging import get_log_level


__all__ = ['UnitTest', 'PerformanceTest', 'SkipTest', 'unittest', 'sizeof']


def setup_logging():
    """Configure a logger to output to stdout."""
    logger = logging.getLogger()
    if logger.handlers:
        return
    logger.setLevel(get_log_level())
    handler = logging.StreamHandler(sys.stdout)
    template = '%(levelname)s %(message)s'
    handler.setFormatter(logging.Formatter(template))
    logger.addHandler(handler)


def create_ssl_certificate(fname):
    """Create a new SSL private key and self-signed certificate, and store
    them both in the file *fname*."""
    try:
        openssl = subprocess.Popen(['openssl', 'req', '-new',
                        '-newkey', 'rsa:1024', '-x509', '-subj', '/CN=test/',
                        '-days', '365', '-nodes', '-batch',
                        '-out', fname, '-keyout', fname],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        sys.stderr.write('Error: openssl not found. SSL tests disabled.\n')
        return
    stdout, stderr = openssl.communicate()
    if openssl.returncode:
        sys.stderr.write('Error: key generation failed\n')
        sys.stderr.write('openssl stdout: {0}\n'.format(stdout))
        sys.stderr.write('openssl stderr: {0}\n'.format(stderr))


def sizeof(obj, exclude=None):
    """Return the size in bytes of *obj*."""
    if obj is None or obj is False or obj is True:
        return 0
    size = sys.getsizeof(obj)
    if hasattr(obj, '__dict__'):
        size += sys.getsizeof(obj.__dict__)
        for key,value in obj.__dict__.items():
            if exclude is not None and key in exclude:
                continue
            size += sizeof(key)
            size += sizeof(value, exclude)
    elif hasattr(obj, '__slots__'):
        for key in obj.__slots__:
            if hasattr(obj, key):
                if exclude is not None and key in exclude:
                    continue
                size += sizeof(getattr(obj, key), exclude)
    return size


class BaseTest(unittest.TestCase):
    """Base class for test suites."""

    @classmethod
    def setUpClass(cls):
        setup_logging()
        testdir = os.path.abspath(os.path.split(__file__)[0])
        os.chdir(testdir)
        if not os.access('testcert.pem', os.R_OK):
            create_ssl_certificate('testcert.pem')
        cls.certname = 'testcert.pem'

    def setUp(self):
        self._tmpindex = 1
        self.__tmpdir = tempfile.mkdtemp('gruvi-test')
        self.__tmpinode = os.stat(self.__tmpdir).st_ino

    def tearDown(self):
        # Some paranoia checks to make me feel better before calling
        # shutil.rmtree()..
        assert '/..' not in self.__tmpdir and '\\..' not in self.__tmpdir
        assert os.stat(self.__tmpdir).st_ino == self.__tmpinode
        try:
            shutil.rmtree(self.__tmpdir)
        except OSError:
            # On Windows a WindowsError is raised when files are
            # still open (WindowsError inherits from OSError).
            pass
        self.__tmpdir = None
        self.__tmpinode = None

    @property
    def tempdir(self):
        return self.__tmpdir

    def tempname(self, name=None):
        if name is None:
            name = 'tmpfile-{0}'.format(self._tmpindex)
            self._tmpindex += 1
        return os.path.join(self.__tmpdir, name)

    def pipename(self, name):
        if sys.platform.startswith('win'):
            return r'\\.\pipe\{0}-{1}'.format(name, os.getpid())
        else:
            return self.tempname(name)

    def assertRaises(self, exc, func, *args, **kwargs):
        # Like unittest.assertRaises, but returns the exception.
        try:
            func(*args, **kwargs)
        except exc as e:
            exc = e
        except Exception as e:
            self.fail('Wrong exception raised: {0!s}'.format(e))
        else:
            self.fail('Exception not raised: {0!s}'.format(exc))
        return exc


class UnitTest(BaseTest):
    """Base class for unit tests."""


class PerformanceTest(BaseTest):
    """Base class for performance tests."""

    def add_result(self, result, params={}, name=None):
        """Add a performance test result."""
        if name is None:
            frame = sys._getframe(1)
            clsname = frame.f_locals.get('self', '').__class__.__name__
            methname = frame.f_code.co_name
            name = '{0}_{1}'.format(clsname[4:], methname[5:]).lower()
        if params is not None:
            params = ','.join(['{0}={1}'.format(k, params[k]) for k in params])
        with open('performance.txt', 'a') as fout:
            fout.write('{0:<32s} {1:<16.2f} {2:s}\n'.format(name, result, params))
