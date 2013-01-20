#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

import gruvi
import gruvi.util


class TestSocket(object):

    def test_send_recv(self):
        hub = gruvi.Hub.get()
        s1 = gruvi.Socket(hub)
        s2 = gruvi.Socket(hub)
        s1.bind(('localhost', 0))
        s1.listen(1)
        counters = [0, 0]
        buf = b'x' * 10000
        def server(sock):
            client, addr = sock.accept()
            while True:
                buf = client.recv()
                if len(buf) == 0:
                    break
                counters[1] += len(buf)
            client.close()
        def client(sock, addr):
            sock.connect(addr)
            for i in range(1000):
                nbytes = sock.send(buf)
                counters[0] += nbytes
            sock.close()
        gr1 = gruvi.Greenlet(hub)
        gr1.start(server, s1)
        gr2 = gruvi.Greenlet(hub)
        gr2.start(client, s2, s1.getsockname())
        hub.switch()
        assert counters[0] == counters[1]
