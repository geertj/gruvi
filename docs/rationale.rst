.. _rationale:

*********
Rationale
*********

Gruvi is an asynchronous I/O library for Python, just like asyncio_, gevent_
and eventlet_. It is therefore a fair to ask why I decided to create a new
library. The short and simple answer is that I didn't agree with some of the
decision decision that went into these other projects, and thought it would be
good to have a library based on different assumptions.

These are the design requirements that I had when creating Gruvi:

* I wanted to use green threads. Compared to Posix threads, green threads are
  very light weight and scalable. Compared to a generator-based ``yield from``
  approach, they provide better ergonomics where there is just one type of
  function, rather than two that cannot easily call into each other.

* I wanted to use libuv_, which is a very high performance asynchronous I/O
  library famous from node.js_, and has excellent cross-platform support
  including Windows.

* I wanted to use a :pep:`3156` style internal API based on transports and
  protocols. This model matches very well with libuv's completion based model.
  Compared to a socket based interface, a transport/completion based interface
  forces a strict separation between "network facing" and "user facing" code.
  In a socket based interface it is easy to make mistakes such as putting a
  socket read deep in some protocol code, and it incentives hacks such as
  monkey patching.

Comparison to other frameworks
******************************

The table below compares some of the design decisions and features of Gruvi
against asyncio_, gevent_ and eventlet_.

Note: tables like these necessarily compress a more complex reality into a much
more limited set of answers, and they also a snapshot in time. Please assume
good faith. If you spot an error in the table, please `let me know`_ and I will
change it.

==================  ==================  ==================  ==================  ==================
Feature             Gruvi               Asyncio             Gevent              Eventlet
==================  ==================  ==================  ==================  ==================
IO library          libuv_              stdlib              libev_              stdlib / libevent_
IO abstraction      Transports /        Transports /        Green sockets       Green sockets
                    Protocols           Protocols
Threading           fibers_             ``yield from``      greenlet_           greenlet_
Resolver            threadpool          threadpool          threadpool /        blocking /
                                                            c-ares_             dnspython_
Python: 2.x         YES (2.7)           YES (2.6+, via      YES                 YES
                                        Trollius_)
Python: 3.x         YES (3.3+)          YES                 NO                  NO
Python: PyPy        NO                  NO                  YES                 YES
Platform: Linux     FAST                FAST                FAST                FAST
Platform: Mac OSX   FAST                FAST                FAST                FAST
Platform: Windows   FAST (IOCP)         FAST (IOCP)         SLOW (select)       SLOW (select)
SSL: Posix          FAST                FAST                FAST                FAST
SSL: Windows        FAST (IOCP)         FAST (IOCP 3.5+)    SLOW (select)       SLOW (select)
SSL: Contexts       YES (also Py2.7)    YES (also Py2.6+)   NO                  NO
HTTP                FAST (via           NO (external)       SLOW (stdlib)       SLOW (stdlib)
                    http-parser_)
Monkey Patching     NO                  NO                  YES                 YES
==================  ==================  ==================  ==================  ==================

Motivations for choosing green threads
**************************************

Green threads have a very low memory overhead, and can therefore support a high
level of concurrently. But more importantly, green threads are cooperatively
scheduled. This means that a thread switch happens only when specifically
instructed by a ``switch()`` call, and with a bit of care, we can write
concurrent code that does not require locking.

When combining a thread implementation with an IO framework, one of the key
design decisions is whether to implement explicit or implicit switching.

Green thread switching in Gruvi is implicit. This means that whenever a
function would block, for example to wait for data from the network, it will
switch to a central scheduler called the *hub*. The hub will then switch to
another green thread if one is ready, or it will run the event loop. A
function that can block is just like any other function. It is called as a
regular function, and can call other (blocking and not) functions.

A common criticism of the implicit switching approach is that the locations
where these switches happen, the so-called *switch points*, are not clearly
marked. As a programmer you could call into a function that 3 levels down in
the call stack, causes a thread switch. The drawback of this, according to the
criticism, is that the switch points could happen essentially anywhere, and
that therefore it's like pre-emptive multi-threading where you need full and
careful locking.

The alternative to implicit switching is explicit switching. This is the
approach taken for example by the asyncio_ framework. In this approach, every
switch point is made explicit, in the case of asyncio because it is not called
as a normal function but instead used with the ``yield from`` construct.

In my view, a big disadvantages of the explicit approach is that the explicit
behavior needs to percolate all the way up the call chain: any function that
calls a switch point also needs to be called as a switch point. In my view this
requires too much up-front planning, and it reduces composability.

Rather than implementing explicit switching, Gruvi sticks with implicit
switching but tries to address the "unknown switch points" problem, in the
following way:

* First, it makes explicit that a switch can only happen when you call a
  function. If you need to change some global state atomically, it is
  sufficient to do this without making function calls, or by doing it in a leaf
  function. In this case, it is guaranteed that no switch will happen.

* Secondly, in case you do need to call out to multiple functions to change a
  shared global state, then as a programmer you need to make sure, by reading
  the documentation of the functions, that they do not cause a switch. Gruvi
  assists you here by marking all switch points with a special decorator.
  This puts a clear notice in the function's docstring. In addition, Gruvi also
  provides a :class:`gruvi.assert_no_switchpoints` context manager that will
  trigger an assertion if a switch point does get called within its body. You
  can use this to be sure that no switch will happen inside a block.

* Thirdly, the "traditional" option, Gruvi provides a full set of
  synchronization primitives including locks that you can use if the two
  other approaches don't work.

In the end, the difference between implicit and explicit switching is a
trade-off. In my view, with the safeguards of Gruvi e.g. the marking of switch
points and the :class:`gruvi.assert_no_switchpoints` context manager, the
balance tips in favor of implicit switching. Some people have come to the same
conclusion, others to a different one. Both approached are valid and as an
programmer you should pick the approach you like most.

Motivations for not doing Monkey patching
*****************************************

One other important design decision in Gruvi that I decided early on is not to
implement *monkey patching*. Monkey patching is an approach employed by e.g.
gevent and eventlet where they make the Python standard library cooperative by
replacing blocking functions with cooperative functions using runtime patching.

In my experience, monkey patching is error prone and fragile. You end up
distributing parts of the standard library yourself, bugs included. This is a
maintenance burden that I'm not willing to take on. Also the approach is very
susceptible to dependency loading order problems, and it only works for code
that calls into the blocking functions via Python. Extension modules using e.g.
the C-API don't work, as well as extension modules that use an external library
for IO (e.g.  psycopg_).

Finally, monkey patching does not work well with libuv because libuv provides a
completion based interface while the standard library assumes a ready-based
interface.

The solution that Gruvi offers is two-fold:

* Either, use Gruvi's own API if available. For example, Gruvi includes classes
  to work with streams and processes, and it also provides an excellent HTTP
  client and server implementation. This is the preferred option.

* When integrating with third-party blocking code, run it in the Gruvi
  maintained thread pool. The easiest way is to call this code via the
  :func:`gruvi.blocking` function.


.. _libuv: https://github.com/joyent/libuv
.. _pyuv: https://pypi.python.org/pypi/pyuv
.. _fibers: https://pypi.python.org/pypi/fibers
.. _gevent: http://gevent.org/
.. _eventlet: http://eventlet.net/
.. _asyncio: http://docs.python.org/3.4/library/asyncio.html
.. _libev: http://libev.schmorp.de/
.. _libevent: http://libevent.org/
.. _c-ares: http://c-ares.haxx.se/
.. _Trollius: https://bitbucket.org/enovance/trollius
.. _greenlet: https://pypi.python.org/pypi/greenlet
.. _node.js: http://nodejs.org/
.. _Julia: http://julialang.org/
.. _http-parser: https://github.com/joyent/http-parser
.. _dnspython: http://www.dnspython.org/
.. _`let me know`: mailto:geertj@gmail.com
.. _psycopg: http://initd.org/psycopg
