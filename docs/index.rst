################
Welcome to Gruvi
################

.. default-domain:: py

Gruvi is a network library for Python. It combines the efficiencies of
event-based I/O with a sequential programming model. Gruvi uses libuv_ (via
pyuv_) as the underlying high-performance event-based I/O layer, and coroutines
based on fibers_ to create a traditional sequential programming model on top
of the evented I/O callback API.

Gruvi comes with batteries included. It has out of the box support for SSL,
HTTP (both client and server), JSON-RPC and D-BUS.

Gruvi values:

* Performance. Gruvi's main dependencies, libuv and fibers, have a very strong
  focus on performance and so does Gruvi itself. Gruvi also contains a very
  fast HTTP implementation based on the Joyent/Node.js event driven
  http-parser_.
* Scalability. Thanks to libuv and the low memory usage of fibers, Gruvi can
  support hundreds of thousands of concurrent connections.
* Platform support. All supported platforms (Posix, Mac OSX and Windows) are
  first-class citizens. This is mostly thanks to libuv.
* Minimalistic design. All of Gruvi is less than 4,000 lines of Python.

Gruvi is similar in concept to gevent_, concurrence_ and eventlet_. For a
rationale on why I've created a new library, see :ref:`rationale`.

Contents
########

.. toctree::
   :maxdepth: 1

   rationale
   install
   tutorial
   concepts
   reference
   changelog

Gruvi is free software, available under the MIT license.

Feel free to contact the author at geertj@gmail.com. You can also submit
tickets or suggenstions for improvements on Github_.

.. _libuv: https://github.com/joyent/libuv
.. _pyuv: http://pyuv.readthedocs.org/en/latest
.. _fibers: http://python-fibers.readthedocs.org/en/latest
.. _gevent: http://gevent.org/
.. _concurrence: http://opensource.hyves.org/concurrence
.. _eventlet: http://eventlet.net/
.. _http-parser: https://github.com/joyent/http-parser
.. _Github: https://github.com/geertj/gruvi
