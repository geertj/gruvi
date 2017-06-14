#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import socket
import unittest

import pyuv
from gruvi import saddr, paddr, getaddrinfo, getnameinfo
from support import UnitTest


class TestSaddr(UnitTest):

    def test_pipe(self):
        self.assertEqual(saddr('/foo'), '/foo')
        self.assertEqual(saddr('/foo/bar'), '/foo/bar')

    def test_ipv4(self):
        self.assertEqual(saddr(('127.0.0.1', 123)), '127.0.0.1:123')

    def test_ipv6(self):
        self.assertEqual(saddr(('::1', 123)), '[::1]:123')

    def test_dns(self):
        self.assertEqual(saddr(('localhost', 123)), 'localhost:123')

    def test_error(self):
        self.assertRaises(TypeError, saddr, 10)
        self.assertRaises(TypeError, saddr, ())


class TestPaddr(UnitTest):

    def test_pipe(self):
        self.assertEqual(paddr('/foo'), '/foo')
        self.assertEqual(paddr('/foo/bar'), '/foo/bar')

    def test_ipv4(self):
        self.assertEqual(paddr('127.0.0.1:123'), ('127.0.0.1', 123))

    def test_ipv6(self):
        self.assertEqual(paddr('[::1]:123'), ('::1', 123))

    def test_dns(self):
        self.assertEqual(paddr('localhost:123'), ('localhost', 123))

    def test_error(self):
        self.assertRaises(TypeError, paddr, 10)
        self.assertRaises(TypeError, paddr, ())
        self.assertRaises(ValueError, paddr, 'localhost:foo')
        self.assertRaises(ValueError, paddr, '[::1:foo')


class TestGetAddrInfo(UnitTest):

    def test_localhost(self):
        result = getaddrinfo('localhost', 'ssh', socktype=socket.SOCK_STREAM)
        self.assertGreater(len(result), 0)
        for res in result:
            self.assertIn(res[0], (socket.AF_INET, socket.AF_INET6))
            self.assertEqual(res[1], socket.SOCK_STREAM)
            self.assertEqual(res[2], socket.IPPROTO_TCP)
            if res[0] == socket.AF_INET:
                self.assertEqual(res[4], ('127.0.0.1', 22))
            else:
                self.assertEqual(res[4], ('::1', 22, 0, 0))

    def test_not_found(self):
        self.assertRaises(pyuv.error.UVError, getaddrinfo, 'localhost', 'does.not.exist')


class TestGetNameInfo(UnitTest):

    def test_localhost(self):
        result = getnameinfo(('127.0.0.1', 22))
        self.assertEqual(result, ('localhost', 'ssh'))


if __name__ == '__main__':
    unittest.main()
