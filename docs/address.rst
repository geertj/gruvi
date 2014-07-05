.. currentmodule:: gruvi

*********
Addresses
*********

Addresses in Gruvi are a location to connect to or listen on. Addresses can be
local (e.g. when using a pipe), or remote (when using TCP or UDP).

The following convention is used throughput Gruvi:

* Pipe addresses are represented as ``str`` or ``bytes`` instances. On Unix
  these represent paths in the file system but on Windows there is no such
  correspondence. On Linux there is a special class of *abstract socket*
  addresses that start with a null byte (``'\x00'``).

* IP addresses are represented as ``(node, service)`` tuples. The format is
  identical for IPv4 and IPv6, and both protocols are supported transparently.
  The host component of the tuple is either DNS name or a string format
  numerical IPv4/IPv6 address, while the port component is either an integer
  port number or a service name.

In addition, some APIs also support connecting to a file descriptor or to a
``pyuv.Stream`` instance.

Name Resolution
===============

IP ``(node, service)`` tuples are resolved to numerical host addresses and port
numbers using the :func:`getaddrinfo` function. The resulting, resolved address
is called a *socket address*, and  should be distinguished from a non-resolved
addressed which we simply call "address".

.. autofunction:: gruvi.getaddrinfo

Note that the distinction between addresses and socket addresses is only
present for IP addresses. Pipes don't use address resolution and their
addresses and socket addresses are the same.

A socket address can be resolved back to an address using :func:`getnameinfo`:

.. autofunction:: gruvi.getnameinfo

Gruvi API function always accept addresses, and address resolution is performed
automatically. The only place where you will work with raw socket addresses is
when you query the address of an existing socket, using e.g. the
:meth:`~BaseTransport.get_extra_info` method of a transport.

Note that the first two elements of an IP socket address are always the
numerical-as-string address and the port number (for both IPv4 and IPv6).
Because :func:`getaddrinfo` also accepts numerical-as-string addresses and port
numbers, they also form a valid address and could be passed back to
:func:`getaddrinfo` again.

Some operating systems support a special convention to specify the scope ID for
an IPv6 addressing using the ``'host%ifname'`` notation where ``'ifname'`` is
the name of a network interface. Support for this is OS specific and neither
libuv nor Gruvi try to present a portable interface for this.

String Addresses
================

Gruvi contains two utility functions to transform addresses to and from a
string representation. This is useful when logging or when accepting addresses
from the command line.

.. autofunction:: gruvi.saddr

.. autofunction:: gruvi.paddr
