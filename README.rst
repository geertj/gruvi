****************
Welcome to Gruvi
****************

Gruvi is a network library for Python. It combines the efficiencies of
event-based I/O with a sequential programming model. Gruvi uses libuv_ (via
pyuv_) as the underlying, high-performance event-based I/O layer, and
greenlets_ to turn the callback programming style associated with event-based
I/O into a traditional sequential programming style. 

Gruvi values:

* Performance. Gruvi's main dependencies, libuv and greenlet, have a very
  strong focus on performance and so does Gruvi itself. Gruvi also contains a
  very fast HTTP implementation based on the Joyent/Node.js event driven
  http-parser_.
* Scalability. Thanks to libuv and the low memory usage of greenlets, Gruvi can
  support hundreds of thousands of concurrent connections.
* Platform support. All supported platforms (Posix, Mac OSX and Windows) are
  first-class citizens. This is mostly thanks to libuv.
* Minimalistic design. All of Gruvi is less than 4,000 lines of Python.

Requirements
************

You need Python 2.6, 2.7 or 3.3+.

The following operating systems are currently tested:

* Posix (Only Linux is currently tested)
* Mac OSX
* Windows (currently untested)

Download
********

Source are available from Github_.

Documentation
*************

The documentation is available on readthedocs_.

License
*******

Gruvi is free software, available under the MIT license.

Contact
*******

Feel free to contact the author at geertj@gmail.com. You can also submit
tickets or suggenstions for improvements on Github_.

.. _libuv: https://github.com/joyent/libuv
.. _pyuv: http://pyuv.readthedocs.org/en/latest
.. _greenlets: http://greenlet.readthedocs.org/en/latest
.. _gevent: http://gevent.org/
.. _concurrence: http://opensource.hyves.org/concurrence
.. _eventlet: http://eventlet.net/
.. _http-parser: https://github.com/joyent/http-parser
.. _Github: https://github.com/geertj/gruvi
.. _readthedocs: https://gruvi.readthedocs.org/
