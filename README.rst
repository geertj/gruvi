Welcome to Gruvi
================

Gruvi is a network library for Python. It combines the efficiencies of evented
I/O with a sequential programming model. Gruvi uses libuv_ (via pyuv_) as the
underlying high-performance evented I/O layer, and coroutines based on fibers_
to create a traditional sequential programming model on top of the evented I/O
callback API.

Gruvi features include:

* A PEP3153_ Transport/Protocol based API, like Twisted_, and asyncio_.
* A sequential programming model using regular Python function calls on top of
  the platform specific evented I/O core. You don't need to use callbacks or
  ``yield from`` to call a potentially blocking operation. When a operation
  would block the current fiber is automatically suspended, and it is resumed
  when the operation completes.
* A high-performance SSL transport implementation.
* A high-performance HTTP protocol client and server protocol implementation,
  based on the node.js http-parser_.
* High performance protocol implementations for D-BUS (client) and JSON-RPC
  (client and server).
* Thread-safe synchronization primitives including locks, signals and queues.
* Uses node.js libuv_ as the I/O core, via pyuv_. This means that gruvi uses
  the I/O model that is most efficient on each platform. On Posix and Mac OSX
  it uses non-blocking I/O via a reactor, while on Windows it uses asynchronous
  ("overlapped") I/O via I/O completion ports.
* Excellent platform support (thanks to libuv_). Posix, Mac OSX and Windows are
  all first-class citizens.
* Support for executing asynchronous functions in a thread or fiber pool using
  a `concurrent.futures`_ API.
* A managed threadpool to integrate with third-party libraries that use
  blocking I/O.

Gruvi is similar in concept to gevent_, concurrence_, eventlet_ and asyncio_,
but has its own unique design. To read more about the differences see the
Rationale_ section in the documentation.

CI Status
---------

.. image:: https://secure.travis-ci.org/geertj/gruvi.png
    :target: http://travis-ci.org/geertj/gruvi

Requirements
------------

You need Python 2.6, 2.7 or 3.3+.

The following operating systems are currently tested:

* Posix (Only Linux is currently tested)
* Mac OSX
* Windows

Installation
------------

Download the source from Github_::

  $ git clone https://github.com/geertj/gruvi
  $ pip install -r requirements.txt
  $ python setup.py build
  $ python setup.py install

To run the test suite::

  $ pip install -r dev-requirements.txt
  $ nosetests

Documentation
-------------

The documentation is available on readthedocs_.

License
-------

Gruvi is free software, available under the MIT license.

Contact
-------

Feel free to contact the author at geertj@gmail.com. You can also submit
tickets or suggestions for improvements on Github_.

.. _libuv: https://github.com/joyent/libuv
.. _pyuv: http://pyuv.readthedocs.org/en/latest
.. _fibers: http://python-fibers.readthedocs.org/en/latest
.. _Twisted: http://twistedmatrix.com/
.. _asyncio: http://docs.python.org/3.4/library/asyncio.html
.. _gevent: http://gevent.org/
.. _concurrence: http://opensource.hyves.org/concurrence
.. _eventlet: http://eventlet.net/
.. _Rationale: http://gruvi.readthedocs.org/en/latest/rationale.html
.. _http-parser: https://github.com/joyent/http-parser
.. _Github: https://github.com/geertj/gruvi
.. _readthedocs: https://gruvi.readthedocs.org/
.. _PEP3153: http://www.python.org/dev/peps/pep-3153/
.. _concurrent.futures: http://docs.python.org/3.4/library/concurrent.futures.html
