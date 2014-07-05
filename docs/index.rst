################
Welcome to Gruvi
################

.. default-domain:: py

Gruvi is an IO library for Python. It combines the efficiencies of event-based
I/O with a sequential programming model. Gruvi uses libuv_ (via pyuv_) as the
underlying high-performance event-based I/O layer, and used coroutines based on
fibers_ to create a traditional sequential programming model on top of the
libuv_ event-based callback model.

Gruvi comes with batteries included. In addition to its base IO support, it
includes robust implementations for important protocols such as SSL/TLS and
HTTP.

Gruvi values:

* Performance. Gruvi's main dependencies, libuv and fibers, have a very strong
  focus on performance and so does Gruvi itself.
* Scalability. Thanks to libuv and the low memory usage of fibers, Gruvi should
  be able to support hundreds of thousands of concurrent connections.
* Platform support. All supported platforms (Posix, Mac OS X and Windows) are
  first-class citizens. This is mostly thanks to libuv.
* Minimalistic design. Gruvi tries to be a small and maintainable framework.

Gruvi is similar in concept to asyncio_, gevent_, and eventlet_. For a
rationale on why I've created a new library, see :ref:`rationale`.

Contents
########

.. toctree::
   :maxdepth: 1

   rationale
   install
   reference
   examples
   changelog

Gruvi is free software, available under the MIT license.

Feel free to contact the author at geertj@gmail.com. You can also submit
tickets or suggestions for improvements on Github_.

.. _libuv: https://github.com/joyent/libuv
.. _pyuv: http://pyuv.readthedocs.org/en/latest
.. _fibers: http://python-fibers.readthedocs.org/en/latest
.. _asyncio: http://docs.python.org/3.4/library/asyncio.html
.. _gevent: http://gevent.org/
.. _concurrence: http://opensource.hyves.org/concurrence
.. _eventlet: http://eventlet.net/
.. _http-parser: https://github.com/joyent/http-parser
.. _Github: https://github.com/geertj/gruvi
