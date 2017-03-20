#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys
import shutil
import socket
import errno
import tempfile
import logging
import subprocess
import pkg_resources
import unittest
import ssl
import six

import gruvi
from gruvi.util import split_cap_words
from gruvi.ssl import create_ssl_context
from gruvi.sync import Event

__all__ = []


def setup_logging():
    """Configure a logger to output to stdout."""
    logger = logging.getLogger()
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    debug = int(os.environ.get('DEBUG', '0'))
    verbose = int(os.environ.get('VERBOSE', '5' if debug else '2'))
    # Smarty-pants way to say 0 = no logs (60), 1 = CRITICAL (50), ... 6 = TRACE (5)
    level = max(5, 10 * (6 - verbose))
    logger.setLevel(level)
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


def create_cmd_wrappers(bindir):
    """On Windows, Create executable file wrappers for our utilities in tests/bin."""
    # This is relevant on Windows only. On Unix our utilities can be executed
    # by uv_spawn() directly.
    #
    # On Windows, a simple solution could be to create .bat file wrappers.
    # However that doesn't work because uv_spawn() uses CreateProcess() which
    # only supports .exe and .com files.
    #
    # The solution is to create little .exe wrapper for each program.
    # Fortunately this is easy. Setuptools contains such a wrapper as a package
    # resource. We need to copy it, and create a basename-script.py wrapper.
    if not sys.platform.startswith('win'):
        return
    shebang = '#!{0}\r\n'.format(sys.executable)
    wrapper = None
    for fname in os.listdir(bindir):
        if '.' in fname:
            continue
        absname = os.path.join(bindir, fname)
        scriptname = absname + '-script.py'
        exename = absname + '.exe'
        if os.access(scriptname, os.R_OK) and os.access(exename, os.X_OK):
            continue
        with open(absname) as fin:
            lines = [line.rstrip() + '\r\n' for line in fin.readlines()]
            lines[0] = shebang
        with open(scriptname, 'w') as fout:
            fout.writelines(lines)
        if wrapper is None:
            wrapper = pkg_resources.resource_string('setuptools', 'cli.exe')
        with open(exename, 'wb') as fout:
            fout.write(wrapper)


def sizeof(obj, exclude=None):
    """Return the size in bytes of *obj*."""
    if obj is None or obj is False or obj is True:
        return 0
    size = sys.getsizeof(obj)
    if hasattr(obj, '__dict__'):
        size += sys.getsizeof(obj.__dict__)
        for key, value in obj.__dict__.items():
            if exclude is not None and key in exclude:
                continue
            s = sizeof(key)
            s += sizeof(value, exclude)
            # print('{}.{}: {}'.format(type(obj).__name__, key, s))
            size += s
    elif hasattr(obj, '__slots__'):
        for key in obj.__slots__:
            if hasattr(obj, key):
                if exclude is not None and key in exclude:
                    continue
                s = sizeof(getattr(obj, key), exclude)
                # print('{}.{}: {}'.format(type(obj).__name__, key, s))
                size += s
    return size


def socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
    """Emulate the Unix socketpair() syscall by connecting an AF_INET socket."""
    # This is useful on platforms like Windows that don't have one.
    # We create a connected TCP socket. Note the trick with setblocking(0)
    # that prevents us from having to create a thread.
    lsock = socket.socket(family, type, proto)
    lsock.bind(('localhost', 0))
    lsock.listen(1)
    addr, port = lsock.getsockname()
    csock = socket.socket(family, type, proto)
    csock.setblocking(False)
    try:
        csock.connect((addr, port))
    except socket.error as e:
        if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINPROGRESS):
            lsock.close()
            csock.close()
            raise
    ssock, _ = lsock.accept()
    csock.setblocking(True)
    lsock.close()
    return (ssock, csock)


class TestCase(unittest.TestCase):
    """Base class for test suites."""

    test_prefix = 'test'

    @classmethod
    def setUpClass(cls):
        setup_logging()
        cls.testdir = os.path.abspath(os.path.split(__file__)[0])
        cls.topdir = os.path.split(cls.testdir)[0]
        os.chdir(cls.testdir)
        certname = 'testcert.pem'
        if not os.access(certname, os.R_OK):
            create_ssl_certificate(certname)
        cls.certname = certname
        bindir = os.path.join(cls.testdir, 'bin')
        path = os.environ.get('PATH', '')
        if bindir not in path:
            create_cmd_wrappers(bindir)
            os.environ['PATH'] = os.pathsep.join([bindir, path])

    def setUp(self):
        self._tmpindex = 1
        self.__tmpdir = os.path.realpath(tempfile.mkdtemp('gruvi-test'))
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
        # Check that no active handles remain. This would mess with other tests.
        hub = gruvi.get_hub()
        active = []
        for handle in hub.loop.handles:
            if not handle.closed and not getattr(handle, '_system_handle', False):
                active.append(handle)
        for handle in active:
            print('closing active handle {0!r}'.format(handle))
            handle.close()
        if active:
            raise RuntimeError('test leaked {0} active handles'.format(len(active)))

    @classmethod
    def setup_loader(cls):
        unittest.TestLoader.testMethodPrefix = cls.test_prefix

    @property
    def tempdir(self):
        return self.__tmpdir

    def tempname(self, name=None):
        if name is None:
            name = 'tmpfile-{0}'.format(self._tmpindex)
            self._tmpindex += 1
        return os.path.join(self.__tmpdir, name)

    def pipename(self, name=None, abstract=False):
        if name is None:
            name = 'tmppipe-{0}'.format(self._tmpindex)
            self._tmpindex += 1
        if sys.platform.startswith('win'):
            return r'\\.\pipe\{0}-{1}'.format(name, os.getpid())
        else:
            prefix = '\x00' if sys.platform.startswith('linux') and abstract else ''
            return prefix + self.tempname(name)

    def get_ssl_context(self):
        context = create_ssl_context(certfile=self.certname, keyfile=self.certname)
        if hasattr(context, 'check_hostname'):
            context.check_hostname = None  # Python 3.4+
        context.verify_mode = ssl.CERT_NONE
        return context

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


class UnitTest(TestCase):
    """Base class for unit tests."""


class PerformanceTest(TestCase):
    """Base class for performance tests."""

    results_name = 'performance.txt'
    test_prefix = 'perf'

    def add_result(self, result, params={}, name=None):
        """Add a performance test result."""
        if name is None:
            frame = sys._getframe(1)
            clsname = frame.f_locals.get('self', '').__class__.__name__
            methname = frame.f_code.co_name
            names = split_cap_words(clsname)
            name = '{0}_{1}'.format(''.join(names[1:]), methname[len(self.test_prefix)+1:]).lower()
        if params is not None:
            params = ','.join(['{0}={1}'.format(k, params[k]) for k in params])
        with open(self.results_name, 'a') as fout:
            fout.write('{0:<32s} {1:<16.2f} {2:s}\n'.format(name, result, params))

    @classmethod
    def start_new_results(cls):
        try:
            os.unlink(cls.results_name)
        except OSError:
            pass


class MemoryTest(PerformanceTest):
    """Special case of a performance test that writes to memory.txt."""

    results_name = 'memory.txt'
    test_prefix = 'mem'


class MockTransport(object):
    """A mock transport.

    All writes are redirected to a BytesIO instance.
    """

    default_write_buffer = 65536

    def __init__(self, mode='rw'):
        self._mode = mode
        self._readable = 'r' in mode
        self._writable = 'w' in mode
        self._protocol = None
        self._error = None
        self._reading = False
        self._writing = False
        self._can_write = Event()
        self._closed = Event()
        self._write_buffer_high = self.default_write_buffer
        self._write_buffer_low = self.default_write_buffer // 2
        self.buffer = six.BytesIO()
        self.eof = False

    def start(self, protocol):
        self._protocol = protocol
        self._protocol.connection_made(self)
        if self._readable:
            self.resume_reading()
        if self._writable:
            self._writing = True
            self._can_write.set()

    def get_write_buffer_size(self):
        return len(self.buffer.getvalue())

    def get_write_buffer_limits(self):
        return self._write_buffer_high, self._write_buffer_low

    def set_write_buffer_limits(self, high=None, low=None):
        if high is None:
            high = self._write_buffer_size
        if low is None:
            low = high // 2
        if low > high:
            low = high
        self._write_buffer_high = high
        self._write_buffer_low = low

    def drain(self):
        self.buffer.seek(0)
        self.buffer.truncate()
        self._can_write.set()
        self._protocol.resume_writing()

    def get_extra_info(self, name, default=None):
        if name == 'unix_creds':
            if hasattr(socket, 'SO_PEERCRED'):
                return (os.getpid(), os.getuid(), os.getgid())
            return default
        else:
            return default

    def pause_reading(self):
        self._reading = False

    def resume_reading(self):
        self._reading = True

    def write(self, buf):
        self.buffer.write(buf)
        if self.get_write_buffer_size() > self.get_write_buffer_limits()[0]:
            self._can_write.clear()
            self._writing = False
            self._protocol.pause_writing()

    def writelines(self, seq):
        for line in seq:
            self.write(line)

    def write_eof(self):
        self.eof = True

    def can_write_eof(self):
        return True

    def close(self):
        self._closed.set()
        self._protocol.connection_lost(None)

    def abort(self):
        self._closed.set()
        self._protocol.connection_lost(None)
