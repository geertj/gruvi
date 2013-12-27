#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import shutil
import tempfile
import logging
import subprocess

if sys.version_info[:2] >= (2,7):
    import unittest
else:
    import unittest2 as unittest

SkipTest = unittest.SkipTest

__all__ = ['UnitTest', 'SkipTest', 'unittest']


def setup_logger(logger):
    """Configure a logger to output to stdout."""
    logger.setLevel(logging.DEBUG)
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


class UnitTest(unittest.TestCase):
    """Base class for unit tests."""

    @classmethod
    def setUpClass(cls):
        cls.__tmpdir = tempfile.mkdtemp('gruvi-test')
        logger = logging.getLogger('gruvi')
        if not logger.handlers:
            setup_logger(logger)
        testdir = os.path.abspath(os.path.split(__file__)[0])
        os.chdir(testdir)
        if not os.access('server.pem', os.R_OK):
            create_ssl_certificate('server.pem')
        cls.certname = 'server.pem'

    @classmethod
    def tearDownClass(cls):
        # Some paranoia checks to make me feel better when calling
        # shutil.rmtree()..
        assert '/..' not in cls.__tmpdir and '\\..' not in cls.__tmpdir
        if '/tmp/' not in cls.__tmpdir and '\\temp\\' not in cls.__tmpdir:
            return
        try:
            shutil.rmtree(cls.__tmpdir)
        except OSError:
            # On Windows a WindowsError is raised when files are
            # still open (WindowsError inherits from OSError).
            pass
        cls.__tmpdir = None

    @classmethod
    def tempname(cls, name):
        return os.path.join(cls.__tmpdir, name)

    @classmethod
    def pipename(cls, name):
        if sys.platform.startswith('win'):
            return r'\\.\pipe\{0}-{1}'.format(name, os.getpid())
        else:
            return cls.tempname(name)

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
