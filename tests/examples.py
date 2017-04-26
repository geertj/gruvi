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
import signal
import unittest

from support import TestCase

import gruvi
from gruvi import Process, PIPE, DEVNULL, StreamClient, HttpClient


class TestExamples(TestCase):
    # Tests for the examples in examples/*

    @classmethod
    def setUpClass(cls):
        super(TestExamples, cls).setUpClass()
        exampledir = os.path.join(cls.topdir, 'examples')
        os.chdir(exampledir)

    def test_curl(self):
        proc = Process(encoding='utf-8')
        proc.spawn([sys.executable, 'curl.py', 'http://www.python.org'], stdout=PIPE)
        stdout, stderr = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(stdout, '')
        proc.close()

    def test_curl_ssl(self):
        proc = Process(encoding='utf-8')
        proc.spawn([sys.executable, 'curl.py', 'https://www.python.org'], stdout=PIPE)
        stdout, stderr = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue('<html' in stdout)
        proc.close()

    def test_echoserver1(self):
        proc = Process(encoding='ascii')
        # -u: unbuffered stdio
        proc.spawn([sys.executable, '-u', 'echoserver1.py'], stdout=PIPE, stderr=DEVNULL)
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
        proc.close()

    def test_echoserver2(self):
        proc = Process(encoding='ascii')
        proc.spawn([sys.executable, '-u', 'echoserver2.py'], stdout=PIPE, stderr=DEVNULL)
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
        proc.close()

    def test_fortune(self):
        proc = Process(encoding='ascii')
        proc.spawn([sys.executable, '-u', 'fortune.py'], stdout=PIPE)
        line = proc.stdout.readline()
        self.assertTrue(line.startswith('Listen on '))
        addr = gruvi.paddr(line[10:])
        client = HttpClient()
        client.connect(addr)
        client.request('GET', '/')
        resp = client.getresponse()
        fortune = resp.body.read().decode('ascii')
        client.close()
        self.assertTrue('Albert Einstein' in fortune)
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)
        proc.close()

    def test_netcat(self):
        proc = Process()
        proc.spawn([sys.executable, '-u', 'netcat.py', 'python.org', '80'], stdin=PIPE, stdout=PIPE)
        proc.stdin.write(b'GET / HTTP/1.1\r\nHost: www.python.org\r\nConnection: close\r\n\r\n')
        result = proc.stdout.read()
        self.assertTrue(b'HTTP/1.1 301' in result)
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)
        proc.close()

    def test_netcat_ssl(self):
        proc = Process()
        proc.spawn([sys.executable, '-u', 'netcat.py', '--ssl', 'python.org', '443'],
                   stdin=PIPE, stdout=PIPE)
        proc.stdin.write(b'GET / HTTP/1.1\r\nHost: www.python.org\r\nConnection: close\r\n\r\n')
        result = proc.stdout.read()
        self.assertTrue(b'<html' in result)
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)
        proc.close()

    def test_jsonrpc(self):
        proc = Process(encoding='utf-8')
        proc.spawn([sys.executable, 'jsonrpc.py'], stdout=PIPE)
        result = proc.stdout.read()
        self.assertEqual(result, 'result = pong\n')
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)
        proc.close()

    def test_http_cs(self):
        proc = Process(encoding='utf-8')
        proc.spawn([sys.executable, 'httpcs.py'], stdout=PIPE)
        result = proc.stdout.read()
        self.assertEqual(result, 'result = pong\n')
        proc.wait(timeout=1)
        self.assertEqual(proc.returncode, 0)
        proc.close()


if __name__ == '__main__':
    unittest.main()
