********
Tutorial
********

This section contains a brief tutorial for those of you who want to dive in
right away. Not all concepts are thoroughly explained here. If something is not
clear consider reading :ref:`Concepts` first.

.. highlight:: python
   :linenothreshold: 10

Tutorial 1: cURL
****************

In this first tutorial, we'll show you how to create a curl like program to
download a single web page. The full source is given below:

.. literalinclude:: ../examples/curl.py

Run the program with::

  $ python curl.py <url>

The program contains some boilerplate regarding argument parsing, which we
won't go into here. We will now go through it section by section.

.. literalinclude:: ../examples/curl.py
   :lines: 6

Here we import the class :class:`~gruvi.http.HttpClient` from :mod:`gruvi.http`.
This shows a few things:

* Protocols typically have client and server classes. In this case, we are
  importing the HTTP client class.
* Protocols live in sub-packages under the :mod:`gruvi` namespace.

The function :func:`~gruvi.http.geturlinfo` is a utility function for
extracting connection information from a URL.

.. literalinclude:: ../examples/curl.py
   :lines: 8

Here we use the :func:`logging.basicConfig` to configure the Python
:mod:`logging` subsystem. Gruvi uses the standard Python logging facility for
all its logging. All log messages are sent to the logger named ``'gruvi'``,
which you can use to customize the output. To get more details, add
``level=logging.DEBUG`` to the call to ``basicConfig``.

.. literalinclude:: ../examples/curl.py
   :lines: 14-15

Here we call our first Gruvi functions. We create a ``HttpClient`` instance,
and then extract connection information from the URL given on the command-line
using ``geturlinfo``. The next line is special:

.. literalinclude:: ../examples/curl.py
   :lines: 16

This is the first time we call into a *switchpoint*. If you look up the
documentation for :meth:`.HttpClient.connect` you will see that it is
marked as such. This means the following:

* The call will block from the application point of view, but not from the
  operating system point of view. Other fibers will be able to run while we are
  blocked here.
* While the connection is being made, the current fiber will be switched out,
  and transfer is controlled to the hub. This is the first time the hub is
  accessed, and it will be created on the fly. Also we didn't create any fibers
  ourselves. This means that the current fiber is the root fiber, which is the
  fiber that corresponds to the program stack that is created by the operating
  system. There is no difference in switching behavior though: the root fiber
  can be switched out just as user created fiber can be.
* Once the connection is established, control will switch back to the point
  just after we got switched out.
* If the connection could not be made, control will also be switched back to
  us, but rather than continue executing, an exception would be raised.

The ``connect`` call is common across many protocol implementations. It
supports TCP, TCPv6, and :class:`~gruvi.pyuv.Pipe` transports (which are Unix
domain sockets on Unix, and named pipes on Windows). To use a TCP or a TCPv6
connection, pass the address as an ``(address, port)`` tuple. The address is
resolved using :func:`~gruvi.util.getaddrinfo`. Depending on the order of the
return values and the OS configuration, this may result in either a TCP or a
TCPv6 connection. To use a pipe, specify the address as a string.

The ``connect`` function also supports SSL. SSL can currently be used only in
conjunction with TCP and TCPv6. To use SSL, pass ``ssl=True``.

.. literalinclude:: ../examples/curl.py
   :lines: 18-19

Here, we see two protocol specific methods. Both are switchpoints. The first
one, :meth:`.HttpClient.request` issues an HTTP request, and will wait until
the request is sent over the network. The second call,
:meth:`.HttpClient.getresponse` will read the headers of a single response from
the connection, and return a :class:`~gruvi.http.HttpResponse` object. These
semantics have the following implications:

* You can easily tell Gruvi to pipeline HTTP requests by issuing multiple
  :meth:`~gruvi.http.HttpClient.request` calls before calling
  :meth:`~gruvi.http.HttpClient.getresponse`.
* The :meth:`~gruvi.http.HttpClient.getresponse` call only reads the HTTP
  header. The HTTP body needs to be read separately. This means that you can
  use Gruvi's HTTP client to efficiently transfer large files.

.. literalinclude:: ../examples/curl.py
   :lines: 21-25

This piece of code is a simple loop that reads chunks from the HTTP body and
writes them to standard output. Two notes about this:

* We specify a buffer size of 4096 bytes. In typical Python fashion, had we not
  specified the buffer size, the entire input would have be read.
* The output is written to standard output using ``print``. Note that this will
  be using blocking I/O. If the standard output buffer gets full, then the
  entire process will be blocked including the current fiber and all other
  fibers. In this case this is OK, because our curl program is a simple client
  with only one execution context. In more complicated situation, you need to
  use asynchronous I/O to standard output. This can be done using the
  :class:`~gruvi.pyuv.TTY` transport.

Tutorial 2: echo server
***********************

In this tutorial we will implement another classic example: the echo server. An
echo server listens on a network port, and echoes any incoming traffic back to
its originator. This tutorial is the first server application we create.

The full source of our echo server is given below:

.. literalinclude:: ../examples/echoserver1.py
   :language: python

Run the echo server with::

  $ python echoserver1.py <port>

The port specifies the port to listen on. Again we will be ignoring some
boilerplate. The first interesting section is this one:

.. literalinclude:: ../examples/echoserver1.py
   :lines: 6-7

Here we see that some things live in the global :mod:`gruvi` namespace as well.
The function :func:`.get_hub` returns a reference to the Hub, and
:mod:`gruvi.util` is a module containing some utility functions.

The second import of :class:`.StreamServer` imports the stream server protocol.
The stream protocol is the simplest protocol possible. It merely interprets its
underlying transport as a sequence of bytes. Being a protocol implementation,
we again see that it lives in its separate module under the ``gruvi``
namespace.

.. literalinclude:: ../examples/echoserver1.py
   :lines: 15-23

Here we define a function that will be used by the :class:`.StreamServer` as
the stream handler. Some notes about this function:

* The handler function takes three arguments. The ``stream`` argument is an
  :class:`io.RawIOBase` instance that can be used to read data from the
  transport. The ``protocol`` argument is a reference to the
  :class:`.StreamServer` instance. And the ``client`` argument is the transport
  that is connecting to the remote client. In this case it will be a
  :class:`~gruvi.pyuv.TCP` instance.
* The function will run in its own fiber. This is automatically taken care of
  by :class:`.StreamServer`.
* The function body contains a simple loop that reads a chunk from the client,
  and echoes its back. Note that both the :meth:`~gruvi.stream.Stream.read` and
  :meth:`~gruvi.stream.Stream.write` invocations are switchpoints. This is OK,
  because the entire function runs in a separate fiber.
* There are two debugging :func:`print` statements. The first one shows the
  address of the remote peer. This uses :meth:`~pyuv.TCP.getpeername` to get
  the remote name and then :meth:`~gruvi.util.saddr` to format it to a string.

.. literalinclude:: ../examples/echoserver1.py
   :lines: 25-26

In these two lines we create the :class:`.StreamServer` instance, and make it
listen on the specified port. The address ``'0.0.0.0 '`` indicates the
*wildcard address* which means to listen on any interface in the system.

.. literalinclude:: ../examples/echoserver1.py
   :lines: 28-29

Here we use :func:`.get_hub` to get a reference to the Hub, and then we switch
to it using :meth:`.Hub.switch`. This does the following:

* Because the hub wasn't used before, the first call to :func:`.get_hub` will
  create it.
* When switching to the hub, it will run its event loop as long as there is
  "something to do". The term "something to do" can be specified more
  accurately, as "as long as there are active handles in the libuv event loop".
  In this case, :class:`.StreamServer` has created a listening socket. This
  socket is a passive socket that will keep the event loop busy until it is
  explicitly closed. Since we never close the socket, the call to
  :class:`~gruvi.Hub.switch` would normally never return.
* The argument ``interrupt=True`` to :meth:`~gruvi.Hub.switch` however tells
  the Hub to switch back to the caller when CTRL-C is pressed.
