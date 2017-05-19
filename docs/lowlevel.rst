****************************************
Transports and protocols (low-level API)
****************************************

.. currentmodule:: gruvi

Gruvi is built around the transport/protocol abstraction layers that are
documented in :pep:`3156` and implemented by asyncio_.

A transport is a standard interface to a communications channel. Different
types of channels implement different interfaces. Since Gruvi uses libuv_ /
pyuv_, its transports are mostly wrappers around the various
:class:`pyuv.Handle` classes. Transport methods are always non-blocking.

A protocol is a callback based interface that is connected to a transport. The
transport calls specific callbacks on the protocol when specific events occur.
The callbacks are always non-blocking, but a protocol may expose certain
protocol operations are part of their API that are switch points.

As a programmer you will use transports and protocols occasionally, but you
will mostly use the higher-level interface provided by Gruvi. The exception is
when adding support for a new protocol.
 
Transports
==========

The following transport classes are available:

.. autoexception:: TransportError()

.. autoclass:: BaseTransport()
    :members:

.. autoclass:: Transport
    :members:

.. autoclass:: DatagramTransport
    :members:

SSL/TLS support
===============

SSL and TLS support is available by means of a special :class:`SslTransport`
transport:

.. autoclass:: SslTransport
    :members:

Protocols
=========

A Protocols is a collection of named callbacks. A protocol is are attached to a
transport, and its callbacks are called by the transport when certain events
happen.

The following protocol classes are available:

.. autoexception:: ProtocolError

.. autoclass:: BaseProtocol
    :members:

.. autoclass:: Protocol
    :members:

.. autoclass:: DatagramProtocol
    :members:

The following class does not exist in :pep:`3156` but is a useful base class
for most protocols:

.. autoclass:: MessageProtocol
    :members:

Creating transports and protocols
=================================

Transports and protocols operate in pairs; there is always exactly one protocol
for each transport. A new transport/protocol pair can be created using the
factory functions below:

.. autofunction:: gruvi.create_connection

.. autofunction:: gruvi.create_server

Endpoints
=========

Endpoints wrap transports and protocols for client and server side connections,
and provide a more object-oriented way of working with them.

.. autoclass:: gruvi.Endpoint
    :members:

.. autoclass:: gruvi.Client
    :members:

.. autoclass:: gruvi.Server
    :members:


.. _libuv: https://github.com/joyent/libuv
.. _pyuv: https://pypi.python.org/pypi/pyuv
.. _asyncio: http://docs.python.org/3.4/library/asyncio.html
