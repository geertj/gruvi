Gruvi - Synchronous evented IO
==============================

Gruvi is a library for doing synchronous evented IO. It is based on greenlet and pyuv.

Gruvi is provided under the MIT license.

The project page can be found on Github at: https://github.com/geertj/gruvi


Installation
============

You need Python >= 2.6. Python 3 is also supported.

Installation using pip:

    $ pip install gruvi

Installation using setuptools::

    $ git clone https://github.com/geertj/gruvi.git
    $ cd gruvi
    $ python setup.py build
    # python setup.py install


Documentation
=============

Gruvi can make evented I/O look like blocking I/O. To do this, the evented I/O
must be executed from within a greenlet. This allows Gruvi to stop and restart
the caller in case the I/O would block. While the I/O is being completed, other
greenlets can run.

The class `Hub` is the central scheduler for all greenlets. It will execute
each greenlet until it blocks, one at a time, until no more greenlets are
active.

Currently Gruvi supports two network classes: `Socket` and `SSLSocket`.
An example echo server:

```python
    import sys
    import gruvi


    class EchoServer(gruvi.Greenlet):

        def __init__(self, hub, address, handler):
            super(EchoServer, self).__init__(hub)
            self.handler = handler
            self.sock = gruvi.Socket(hub)
            self.sock.bind(address)
            self.sock.listen(100)
            self.address = self.sock.getsockname()
            sys.stdout.write('listening on %s:%d\n' % self.address)

        def run(self):
            while True:
                conn, addr = self.sock.accept()
                handler = self.handler(self.hub, conn, addr)
                handler.start()


    class EchoHandler(gruvi.Greenlet):

        def __init__(self, hub, conn, addr):
            super(EchoHandler, self).__init__(hub)
            self.conn = conn
            self.address = addr

        def run(self):
            sys.stdout.write('START client %s:%d\n' % self.address)
            while True:
                buf = self.conn.recv()
                if buf == '':
                    break
                self.conn.sendall(buf)
            self.conn.close()
            sys.stdout.write('DONE client %s:%d\n' % self.address)


    hub = gruvi.Hub.get()
    server = EchoServer(hub, ('localhost', 0), EchoHandler)
    server.start()
    hub.switch()
```


Feedback
========

You can reach me at <geertj@gmail.com>.
