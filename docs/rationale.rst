.. _rationale:

*********
Rationale
*********

This section gives a technical overview of Gruvi and explains some of its
design decisions and their rationale. To get started immediately, skip to the
:ref:`installation` and :ref:`tutorial` sections.

Gruvi is a network library for Python. It combines the efficiencies of evented
I/O with a sequential programming model. Gruvi uses libuv_ (via pyuv_) as the
underlying high-performance evented I/O layer, and coroutines based on fibers_
to create a traditional sequential programming model on top of the evented I/O
callback API.

Gruvi is similar in concept to gevent_, concurrence_, eventlet_ and asyncio_.
There are a few important differences however that distinguish Gruvi from these
frameworks.

* Gruvi has excellent cross-platform support. This is mostly thanks to libuv.
  All supported platforms, Posix, Windows and Mac OSX, are first class citizens.
  With other libraries Windows is often poorly supported because it does not
  support efficient ready-based IO multiplexing primitives (e.g.  ``epoll()``
  or ``kqueue()``).

* There is no platform abstraction layer. Libuv is already a proper
  cross-platform abstraction layer. Gruvi does not try to hide or abstract away
  the fact that it is based on libuv. In order to use Gruvi, you need to know
  the basics of both pyuv and libuv. It is perfectly idiomatic Gruvi code to
  mix imports and use of pyuv and Gruvi in the same program.

* Gruvi wants to be a minimal framework. The Gruvi source is less that 5,000
  lines of Python code (tests, and 3rd-party code excluded).

* Gruvi does not offer *monkey patching*. Monkey patching is an approach
  employed by e.g. gevent and eventlet where they try to make the Python
  standard library cooperative by changing blocking functions with cooperative
  functions at run time. In my view, monkey patching is error prone and
  fragile. In addition, monkey patching does not work well with libuv because
  libuv provides a completion based interface while the standard library
  assumes a ready-based interface  (for example ``read()`` and ``recv()``).

  Instead of monkey patching, Gruvi implements its own API based on the PEP
  3153 Transport/Protocol abstraction. This API is a lot more natural within
  the context of fibers and libuv.

* No special syntax is required to call functions that can potentially block.
  If a blocking operation happens, the current fiber is automatically suspended
  until the operation completes (or times out). This is different from
  generator based frameworks (like asyncio) where you use a special ``yield``
  or ``yield from`` syntax to call out to potentially blocking functions.

* Gruvi comes with batteries included. At the moment, it ships with an HTTP
  client and server, a D-BUS client, and a JSON-RPC client and server.

.. _libuv: https://github.com/joyent/libuv
.. _pyuv: http://pyuv.readthedocs.org/en/latest
.. _fibers: http://python-fibers.readthedocs.org/en/latest
.. _gevent: http://gevent.org/
.. _concurrence: http://opensource.hyves.org/concurrence
.. _eventlet: http://eventlet.net/
.. _asyncio: http://docs.python.org/3.4/library/asyncio.html
