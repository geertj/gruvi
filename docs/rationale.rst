.. _rationale:

*********
Rationale
*********

This section gives a technical overview of Gruvi and explains some of its
design decisions and their rationale. To get started immediately, skip to the
:ref:`introduction` section.

Gruvi is a network library for Python. It combines the efficiencies of
event-based I/O with a sequential programming model. Gruvi uses libuv_ (via
pyuv_) as the underlying, high-performance event-based I/O layer, and fibers_
to turn the callback programming style associated with event-based I/O into a
traditional sequential programming style. 

Gruvi is similar in concept to gevent_, concurrence_ and eventlet_. There are
a few important differences however that distinguish Gruvi from these other
frameworks.

* Gruvi has excellent cross-platform support. This is mostly thanks to libuv.
  All supported platforms, Posix, Windows and Mac OSX, are first class citizens.
  With other libraries Windows is often poorly supported because it does not
  support efficient ready-based IO multiplexing primitives (i.e. ``poll()``,
  ``epoll()`` or ``kqueue()``).

* There is no platform abstraction layer. Libuv is already a proper
  cross-platform abstraction layer. Gruvi does not try to hide or abstract away
  the fact that it is based on libuv. In order to use Gruvi, you need to know
  the basics of both pyuv and libuv. It is perfectly idiomatic Gruvi code to
  mix imports and use of pyuv and Gruvi in the same program.

* Gruvi wants to be a minimal framework. The Gruvi source is less that 4,000
  lines of Python code (tests, and 3rd-party code excluded).

* Gruvi does not offer *monkey patching*. Monkey patching is an approach
  employed by e.g. gevent and eventlet where they try to make the Python
  standard library cooperative by changing blocking functions with cooperative
  functions at run time. In my view, monkey patching is error prone and
  fragile. In addition, monkey patching does not work well with libuv because
  libuv provides a completion based interface while the standard library
  usually assumes a ready-based interface  (for example ``read()`` and
  ``recv()``).

  Instead of monkey patching, Gruvi implements its own, custom API that has
  been specifically designed to work well within the context of fibers and
  libuv.

.. _libuv: https://github.com/joyent/libuv
.. _pyuv: http://pyuv.readthedocs.org/en/latest
.. _fibers: http://python-fibers.readthedocs.org/en/latest
.. _gevent: http://gevent.org/
.. _concurrence: http://opensource.hyves.org/concurrence
.. _eventlet: http://eventlet.net/
