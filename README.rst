Welcome to Gruvi
================

Gruvi is an IO library for Python. It uses libuv_ (via pyuv_) as the underlying
high-performance event-based I/O layer, and coroutines based on fibers_ to
create a traditional sequential programming model on top of the libuv_
event-based callback model.

Gruvi is similar in concept to asyncio_, gevent_, and eventlet_. For a
rationale on why I've created a new library, see the Rationale_ section in the
manual.

Features
--------

Gruvi has the following features:

* Excellent platform support (mostly thanks to libuv). Linux, Mac OSX and
  Windows are all first-class citizens. On Windows IOCP is used meaning that
  you don't run into the scalability limitations of ``select()`` there.
* Small core and focus on low memory usage and fast performance. This makes
  Gruvi very suitable for mobile applications and embedded web servers.
* Great support for SSL, also on Windows. Includes an SSL backports module
  that makes certain 3.x features available on Python 2.7.
* Built-in client/server support for HTTP, JSON-RPC and D-BUS.
* PEP-3156 compatible transport/protocol interface.
* Transparent concurrency support. Thanks to fibers, calling into a blocking
  function is just like calling into a regular function.
* Thread synchronization primitives including locks, conditions and queues.
* Thread and fiber pools with a ``concurrent.futures`` interface.

CI Status
---------

.. image:: https://secure.travis-ci.org/geertj/gruvi.png
    :target: http://travis-ci.org/geertj/gruvi

Example
-------

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
  gruvi.get_hub().switch()


Requirements
------------

You need Python 2.7 or 3.3+.

The following operating systems are currently tested:

* Posix (Only Linux is currently tested)
* Mac OSX
* Windows

Installation
------------

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
.. _asyncio: http://docs.python.org/3.4/library/asyncio.html
.. _gevent: http://gevent.org/
.. _eventlet: http://eventlet.net/
.. _Rationale: http://gruvi.readthedocs.org/en/latest/rationale.html
.. _Installation: http://gruvi.readthedocs.org/en/latest/install.html
.. _StreamServer: http://gruvi.readthedocs.org/en/latest/streams.html
.. _readthedocs: https://gruvi.readthedocs.org/
.. _Github: https://github.com/geertj/gruvi
