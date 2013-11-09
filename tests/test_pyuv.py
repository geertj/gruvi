#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import gruvi
from gruvi.stream import StreamClient, StreamServer
from support import *


def echo_handler(stream, protocol, client):
    while True:
        buf = stream.read(4096)
        if not buf:
            break
        nbytes = stream.write(buf)


class TestHandles(UnitTest):

    def test_tcp(self):
        server = StreamServer(echo_handler)
        server.listen(('localhost', 0))
        addr = server.transport.getsockname()
        client = StreamClient()
        client.connect(addr)
        buf = b'x' * 1024
        client.write(buf)
        result = client.read(1024)
        self.assertEqual(result, buf)
        client.close()

    def test_pipe(self):
        server = StreamServer(echo_handler)
        path = self.pipename('temp.sock')
        server.listen(path)
        client = StreamClient()
        client.connect(path)
        buf = b'x' * 1024
        client.write(buf)
        result = client.read(1024)
        self.assertEqual(result, buf)
        client.close()


if __name__ == '__main__':
    unittest.main(buffer=True)
