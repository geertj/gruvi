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
import signal

from support import TestCase, unittest
from test_process import create_cmd_wrappers

import gruvi
from gruvi import Process, PIPE, StreamClient, HttpClient


class TestExamples(TestCase):
    # Tests for the examples in examples/*

    @classmethod
    def setUpClass(cls):
        super(TestExamples, cls).setUpClass()
        # Add tests/bin to $PATH for the "fortune" program
        bindir = os.path.join(cls.testdir, 'bin')
        create_cmd_wrappers(bindir)
        path = os.environ['PATH']
        if bindir not in path:
            os.environ['PATH'] = os.pathsep.join([bindir, path])
        exampledir = os.path.join(cls.topdir, 'examples')
        os.chdir(exampledir)

    def test_curl(self):
        proc = Process(encoding='utf-8')
        proc.spawn([sys.executable, 'curl.py', 'http://xkcd.org'], stdout=PIPE)
        stdout, stderr = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue('<html' in stdout)

    def test_curl_ssl(self):
        proc = Process(encoding='utf-8')
        proc.spawn([sys.executable, 'curl.py', 'https://xkcd.org'], stdout=PIPE)
        stdout, stderr = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue('<html' in stdout)

    def test_echoserver1(self):
        proc = Process(encoding='ascii')
        # -u: unbuffered stdio
        proc.spawn([sys.executable, '-u', 'echoserver1.py'], stdout=PIPE)
        line = proc.stdout.readline()
        self.assertTrue(line.startswith('Listen on '))
        addr = gruvi.paddr(line[10:])
        client = StreamClient()
        client.connect(addr)
        client.write(b'foo')
        self.assertEqual(client.read(3), b'foo')
        client.write(b'foo bar baz\n')
        self.assertEqual(client.readline(), b'foo bar baz\n')
        client.close()
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=2)
        self.assertEqual(proc.returncode, 0)

    def test_echoserver2(self):
        proc = Process(encoding='ascii')
        proc.spawn([sys.executable, '-u', 'echoserver2.py'], stdout=PIPE)
        line = proc.stdout.readline()
        self.assertTrue(line.startswith('Listen on '))
        addr = gruvi.paddr(line[10:])
        client = StreamClient()
        client.connect(addr)
        client.write(b'foo')
        self.assertEqual(client.read(3), b'foo')
        client.write(b'foo bar baz\n')
        self.assertEqual(client.readline(), b'foo bar baz\n')
        client.close()
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)

    def test_fortune(self):
        proc = Process(encoding='ascii')
        proc.spawn([sys.executable, '-u', 'fortune.py'], stdout=PIPE)
        line = proc.stdout.readline()
        self.assertTrue(line.startswith('Listen on '))
        addr = gruvi.paddr(line[10:])
        client = HttpClient()
        client.connect(addr)
        client.request('GET', '/')
        response = client.getresponse()
        fortune = response.read().decode('ascii')
        client.close()
        self.assertTrue('Albert Einstein' in fortune)
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)

    def test_netcat(self):
        proc = Process()
        proc.spawn([sys.executable, '-u', 'netcat.py', 'xkcd.com', '80'], stdin=PIPE, stdout=PIPE)
        proc.stdin.write(b'GET / HTTP/1.1\r\nHost: xkcd.com\r\nConnection: close\r\n\r\n')
        result = proc.stdout.read()
        self.assertTrue(b'<html' in result)
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)

    def test_netcat_ssl(self):
        proc = Process()
        proc.spawn([sys.executable, '-u', 'netcat.py', '--ssl', 'xkcd.com', '443'],
                   stdin=PIPE, stdout=PIPE)
        proc.stdin.write(b'GET / HTTP/1.1\r\nHost: xkcd.com\r\nConnection: close\r\n\r\n')
        result = proc.stdout.read()
        self.assertTrue(b'<html' in result)
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)


if __name__ == '__main__':
    unittest.main()
