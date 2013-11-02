.. module:: gruvi

.. _concepts:

********
Concepts
********

This section introduces the most important concepts in Gruvi. It is recommended
to have a proper understanding of this chapter before going ahead with the API
reference. If you are already familiar with fibers and event based I/O, you
can probably pass over this section rather quickly.

Blocking I/O vs Callbacks
*************************

Gruvi is a network library. By their very nature, network operations take take
to complete. For example, let's look at what is required to download a web
page via the HTTP protocol. At a low level, this involves the following steps:

1. A DNS lookup needs to performed to resolve a network location. This involves
   at least one network round trip to a name server.
2. A TCP connection needs to be established. This involves the TCP 3-way
   handshake.
3. An SSL security context may need to be established. This involves the SSL
   handshake protocol.
4. The HTTP request is sent over.
5. The server parses the request, and generates a response.
6. The client receives the response.
7. SSL may need to be torn down. This involves the SSL close_notify alert.
8. The TCP connection may need to be closed. This involves a 4-way handshake.

We will call the function that downloads a web page by performing all of the
above ``get_web_page()``. We'll use it as an example in the sections below.

Any API for network operations needs to take into account that network
operations take time to complete. There are a few ways in which APIs have been
designed to handle this.  Note that we're talking primarily about high-level
APIs like our example ``get_web_page()``. For low-level operation system APIs
see the next section.

The simplest type of API is a *Blocking API*. With a blocking API, the API call
waits until the entire operation is complete. So if our ``get_web_page()``
function were to implement a blocking API, it would take however long it needed
to complete the operation, and only return when it's done. In the mean time,
nothing else can be done, at least not in the execution context where the
function is blocked.

Blocking I/O has the advantage of being easy to understand and to program for.
The disadvantage is that for all but the simplest program, you will need
multiple concurrent execution contexts to handle all the I/O you need to do. And
depending on the type of execution context (e.g. threads, processes, or
fibers) there could be a large overhead, or it could introduce the need for
complicated locking.

The second type of API that is frequently used is a *Callback API*. In a
callback API, our function ``get_web_page()`` would immediately return and
never block. It would take a ``callback`` parameter that we would provide with
a callback function. The function will be called at some future point when the
operation is complete.

The advantage of a callback API is that it is usually more efficient. This is
because there is just one execution context, and so the memory overhead
associated with multiple execution contexts is not there. Also because there
is just one context, locking is not usually required to synchronize access to
shared state. The disadvantage of a callback style API is that it lead to
spaghetti like code where statements that logically come one after the other,
are not sequential in your source code.

Low-level I/O
*************

Usually, (but not in the case of Gruvi! We'll get to that below.) blocking APIs
are implemented using low-level blocking I/O primitives provided by the
operation system. Examples of such primitives are for example ``read()`` and
``recv()`` when used with a file descriptor with the ``O_NONBLOCK`` flag unset.
In this case, we need multiple execution contexts for all but the simplest
programs, to allow that work can be performed while one execution context is
blocked. Often threads are used for this.

Threads however have serious drawbacks. Gruvi was written with the opinion that
threads are a bad solution for I/O. This is because threads have a high memory
overhead (in the order of megabytes), which limits the total number of threads
you can have in a system. And threads often introduce the need for locking,
with is very difficult to get right. For a more authoritative opinion on why
threads are usually bad, see `this paper by Ousterhout`. Note that Gruvi is not
of the opinion that threads are always bad, just when used for I/O. An example
where I believe that threads are a good solution is number crunching on either
a large shared state (for efficiency), or without any shared state (no need for
locks).

When not using threads, we need a way to handle multiple I/O operations in a
single execution context. This is called *I/O multiplexing*. There are two
primary types of APIs for I/O multiplexing that are efficient and offered by
modern operating systems today:

1. *Completion based*. In this case, an operating system routine (system call
   or low-level library function) is passed a callback. The routine returns
   immediately, and the callback is called at a later time when the operation
   has completed.

2. *Ready based*. In this case, a separate operating system routine is used
   to register I/O operations, and wait for any of them to become ready for I/O.
   The system calls used in this case are for example ``select()`` and
   ``poll()``.

Unfortunately none of these 2 APIs is available on all the three major
operating systems in use today. Posix and Mac OSX have good and efficient
ready-based I/O primitives. Windows has ready-based I/O as well (e.g.
``WSAPoll``), but it is not efficient and known to be buggy. The only efficient
I/O on Windows is completion based I/O.

Fortunately it is easy to turn ready-based I/O in completion based I/O. You just
poll which operations are ready, do them, and then call the callback from user
space. The other way around, turning completion based I/O into ready-based I/O,
is not easy to do efficiently.

This therefore is the approach that libuv_ takes. It provides a
completion-based, callback style API. On Windows this uses the native Windows
completion based I/O machinery. And on Posix/Mac, it uses the native
ready-based I/O primitives which can be efficiently transformed in completion
based primitives.

Fibers
******

Fibers are user-mode execution contexts that are explicitly created and
scheduled by application code. In a program without fibers, you can visualize
the execution state of a program as a single stack of function calls, starting
from a ``main()`` function or equivalent, all the way down to the currently
executing function. Calling a new function pushes a frame on the stack,
returning from a function pops a frame from this stack.

In a program with fibers, the execution state of the program is a
generalization of the picture above: rather than one stack, there are multiple
stacks. The stack are independent, and each one corresponds to one execution
context. In addition to calling a function and returning, a fiber can also
create a new stack and/or switch to it. In other words, fibers are
*coroutines*.

Fibers are similar to threads in the fact that both represent independent
execution contexts. However there are two big differences:

1. There is always exactly one fiber that is executing at the same time,
   even of multiple CPU cores.
2. Switching between fibers only happens when a ``switch()`` function is
   called. In case of threads the switching may done implicitly by the OS or
   thread library scheduler at any time during program execution.

This above differences result in two large advantages of fibers when
compared to threads:

1. Because fibers are scheduled in user mode, a technique called *stack
   splicing* can be used. This technique removes the need to preallocate
   program stacks. Each fiber will only use the stack space that is actually
   occupied. This is typically a few orders of magnitude smaller than the stack
   space allocated for threads. The direct consequence is that the number of
   concurrent fibers on a single system can be a few orders of magnitude
   higher than the number of concurrent threads. This in turn makes it possible
   to write network servers where each connection is handled by a single
   fiber, greatly simplifying the architecture.
2. Because switching is explicit, usually it is possible to write programs that
   do not require locks. When using threads, switching is implicit i.e. it can
   happen anywhere in your program. This usually means that locks are required.

The Gruvi API
*************

The Gruvi API logically consists of two parts: a transport API, and a protocol
API.

The transport API conceptually sits at the lowest level. It deals with the
actual mechanics of interfacing with the operating system to perform I/O. The
transport API is a completion-based, callback style API. For the most part, it
is directly imported from pyuv_. Gruvi does not try to abstract away the fact
that it's based on pyuv, and it is perfectly idiomatic Gruvi code to freely mix
pyuv and Gruvi API calls.

The protocol API conceptually sits on top of the transport API. The protocol
API deals with the specifics around protocol interactions. For example, the
HTTP client protocol that is provided by Gruvi provides a function to issue an
HTTP request. The protocol API is a blocking API. For the most part this is is
fully transparent as protocol handlers are automatically run in their own
fiber.

The protocol API is what you'd normally use as a programmer. Occasionally you
might drop down to the transport API, for example if you want to create a new
protocol.

The Gruvi API has this dual nature in order to combine the efficiencies of
non-threaded, multiplexed I/O at the operating system level, with a traditional
and easy to use blocking API at the protocol level.

The Hub and Fiber Scheduling
****************************

What happens when a function in the protocol API needs to block? In short, what
happens is that the current fiber's execution will be suspended, and that we
switch to a central fiber scheduler call the *Hub* (called after the name it
has in gevent).

The Hub runs in a separate fiber. It maintains a libuv event loop into which
all wakeup conditions are registered as callbacks. The protocol implementations
are responsible for setting up their own wakeup conditions. When a protocol
operation needs to call a callback style transport API function, it will take
the following three steps:

1. It will ask the Hub for a special "switchback" callback. This is a callback
   that, when called, will switch back to the current fiber.
2. It will call the transport level API with the switchback callback as the
   callback. This operation returns immediately.
3. It will switch to the Hub.

The Hub's main loop simply calls the libuv event loop repeatedly. Once the
wakeup condition associated with a transport API call has become true, libuv
will call the associated callback. This will be the "switchback" callback,
which will resume execution in the fiber just after it switched to the Hub.

If it sounds pretty straightforward, that is because it is. The above is all
that is required to make multiple fibers work together cooperatively on top
of an event based API.

.. _lockless:

Lockless operation
******************

One of the biggest advantages of fibers is that with a some effort, it is
possible to write lockless concurrent programs. The idea behind lockless
operation with fibers is that there are no implicit context switches. All
switches happen at well defined points in time, namely when the
:meth:`gruvi.Fiber.switch` function is called. This means that if we can
prevent this method from being called (either directly or indirectly) when
updating a shared state in a non-atomic way, then the update will be safe and
we can do it without locks.

A trivial way to achieve not calling ``switch()``, is to simply not call any
functions when updating a shared state. While this is a fool proof way, it is
not always practical. If do you need to call functions when updating a shared
state, the  Gruvi provides some infrastructure to help you with this.

First, all methods in Gruvi that can potentially cause a switch are decorated
with the :meth:`switchpoint` decorator. We'll call these methods switchpoints
from now on. All methods that are switchpoints are clearly documented as such
in the Gruvi documentation. This will help you determining if it is safe to
call a certain method or not. Things can still go wrong because you might call
a Gruvi switchpoint indirectly via a function. For this case, Gruvi provides
the :meth:`assert_no_switchpoints` context manager. This context manager
asserts that no switchpoint will be called in its block.  For example::

    with assert_no_switchpoints():
        do_one_thing()
        do_another_thing()

It is important to note that ``assert_no_switchpoints()`` is an assertion (as
its name implies), and not a lock. If a switchpoint is encountered in the
block, even if it does not result in a switch, then a ``RuntimeError`` will be
raised.

It is probably best to be conservative when making non-atomic updates to shared
state, and try to confine them as much as possible to leaf functions. If that's
not possible however, the Gruvi documentation and the
``assert_no_switchpoints`` context manager can be used to add an extra level of
safety.

Transports
**********

As mentioned above, the Gruvi transport API is a low-level, callback style API.
The transport API defines multiple types of transports. Each transport
represents a specific type of channel over which data can be sent. If you
haven't read the pyuv_ documentation yet, now would be a good time to do that.
Almost the entire transport level API in Gruvi (except :class:`ssl.SSL`) is
provided by pyuv.

Transports are created and used by protocol implementations. Normally you would
not use transports a lot (unless you are writing a new protocol in which case
you may use them extensively). However there's a few places in the protocol API
where transports show up:

* Protocols have a ``transport`` property that returns the transports over
  which the protocol runs.
* Server-side protocols have a ``clients`` property which is a set containing
  the transports of all connected clients.
* Some methods on server-side protocols accept a ``client`` parameter that
  indicates which client to operate on. This will always be an element in the
  ``clients`` property.

Methods on transports are never switchpoints. Either they complete immediately,
or take a callback parameter.

Protocols
*********

The Gruvi protocol API is the central part of Gruvi. It provides a set of
network protocol implementations using a blocking API. Most protocols have
separate client and server classes. Protocols may contain methods that are
switchpoints. Examples of supported protocols are :mod:`gruvi.http`,
:mod:`gruvi.jsonrpc` and :mod:`gruvi.dbus`.

Protocols in Gruvi have a few common methods such as ``connect()`` or
``listen()``.  In addition to these methods, they implement protocol specific
operations as custom methods. For example the JSON-RPC client protocol has a
``call_method()`` method to invoke a remote procedure call and wait for its
result.

.. _libuv: https://github.com/joyent/libuv
.. _pyuv: http://pyuv.readthedocs.org/en/latest
.. _this paper by Ousterhout: www.stanford.edu/class/cs240/readings/threads-bad-usenix96.pdf
