**************************************
Gruvi: Async IO for Python, Simplified
**************************************

.. image:: https://secure.travis-ci.org/geertj/gruvi.png
    :target: http://travis-ci.org/geertj/gruvi

.. image:: https://coveralls.io/repos/geertj/gruvi/badge.png?branch=master
    :target: https://coveralls.io/r/geertj/gruvi?branch=master 

.. image:: https://badge.fury.io/py/gruvi.png
    :target: http://badge.fury.io/py/gruvi

Improved ergonomics for Python programmers using asynchronous IO.

Gruvi is an asynchronous IO library for Python. It focuses on the following
desirable properties:

* *Simple*. Async IO code should look just like normal code, with simple,
  sequential control flow and regular functions.

* *Efficient*. An IO library should have a very low memory and CPU overhead,
  so that it can scale to small systems or to many concurrent connections.

* *Powerful*. Common protocols like SSL/TLS and HTTP should be part of every
  IO library.

Gruvi uses libuv_ (via pyuv_) as the underlying high-performance event-based
I/O layer, and coroutines based on fibers_ to create a traditional sequential
programming model on top of the libuv_ completion/callback model.

Gruvi is similar in concept existing async IO frameworks like asyncio_,
gevent_, and eventlet_. For a comparison, see Rationale_.

Features
========

Gruvi has the following features:

* Excellent platform support (mostly thanks to libuv). Linux, Mac OSX and
  Windows are all first-class citizens.
* PEP-3156 compatible transport/protocol interface.
* A traditional, sequential programming model based on green threads, where
  there is no distinction between asynchronous and normal functions.
* Great SSL/TLS support, also on Windows. The `asynchronous SSL`_ support in the
  Python standard library came from Gruvi before it was included into the stdlib.
* Small core and focus on low memory usage and fast performance. This makes
  Gruvi very suitable for mobile applications and embedded web servers.
* A full suite of synchronization primitives including locks, conditions and queues.
* Thread and fiber pools with a ``concurrent.futures`` interface.
* Batteries includes: built-in client/server support for HTTP, JSON-RPC and D-BUS.
* Support for Python 2.7.x and 3.3+.

Example
=======

An simple echo server, using a StreamServer_::

  import gruvi

  def echo_handler(stream, transport, protocol):
      while True:
          buf = stream.read1()
          if not buf:
              break
          stream.write(buf)

  server = gruvi.StreamServer(echo_handler)
  server.listen(('localhost', 7777))
  server.run()


Requirements
============

You need Python 2.7 or 3.3+.

The following operating systems are currently supported:

* Linux (might work on other Posix OSs)
* macOS (not currently tested via CI)
* Windows (not currently tested via CI)

Installation
============

Development install in a virtualenv::

  $ git clone https://github.com/geertj/gruvi
  $ cd gruvi
  $ pip install -r requirements.txt
  $ python setup.py build
  $ python setup.py install

To run the test suite::

  $ python runtests.py unit

For other installation options, see the Installation_ section in the manual.

Documentation
=============

The documentation is available on readthedocs_.

License
=======

Gruvi is free software, provided under the MIT license.

Contact
=======

Feel free to contact the author at geertj@gmail.com. You can also submit
tickets or suggestions for improvements on Github_.

.. _libuv: https://github.com/libuv/libuv
.. _pyuv: http://pyuv.readthedocs.org/en/latest
.. _fibers: http://python-fibers.readthedocs.org/en/latest
.. _asyncio: http://docs.python.org/3.4/library/asyncio.html
.. _gevent: http://gevent.org/
.. _eventlet: http://eventlet.net/
.. _Rationale: http://gruvi.readthedocs.org/en/latest/rationale.html
.. _asynchronous SSL: https://docs.python.org/3/library/ssl.html#ssl.SSLObject
.. _StreamServer: http://gruvi.readthedocs.org/en/latest/streams.html
.. _Installation: http://gruvi.readthedocs.org/en/latest/install.html
.. _readthedocs: https://gruvi.readthedocs.org/
.. _Github: https://github.com/geertj/gruvi
