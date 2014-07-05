Fibers and the Hub
==================

.. currentmodule:: gruvi

Fibers are light weight execution contexts that are cooperatively scheduled.
They form the basis for concurrency in Gruvi. Comparing fibers to threads:

* Like threads, fibers represent an independent flow of control in a program.
* Fibers are more light weight than threads, meaning you can run more of them.
* Unlike threads, there can only ever be one active fiber (per thread, see
  below). This means that fibers give you *concurrency* but not *parallelism*.
* Unlike threads, fibers are cooperatively scheduled. They are never preempted
  and have to yield control other fibers explicitly (called *switching*).

Gruvi uses the python-fibers_ package as its fiber library.

Fibers logically exist within threads. Each fiber has its own Python and
C-level stack. When a Python program starts, there will be one thread called
``'Main'``, and this thread will have one fiber called ``'Root'``. Both are
created automatically; the main thread by Python and the root fiber by the
python-fibers package.

Fibers are organized in a tree. Each fiber except the root fiber has a parent.
When a fiber exits, either because its main function exits or because of an
uncaught exception, control is passed to its parent. If the root fiber exits,
the thread will exit.

The hub and fiber scheduling
----------------------------

The Gruvi framework maintains a special fiber called the *Hub*. The hub runs an
*event loop*, and acts as a central fiber scheduler. The event loop in Gruvi is
provided by libuv_ through the pyuv_ bindings.

From a high-level, the flow of a Gruvi program is as follows:

1. Run the current fiber (initially the root fiber).
2. When the fiber needs to wait for something, for example network data,
   the event to wait for is registered with the event loop, together with a
   *switch back* callback.
3. The fiber switches to the hub, which run the event loop.
4. When the event loop detects an event for which a fiber registered interest,
   it will will call the callback. This causes a switch back to the fiber that
   installed the event.

The hub instance is automatically created when in is first needed. It can be
retrieved using the following function:

.. autofunction:: gruvi.get_hub

The event loop is available as the ``.loop`` property:

.. autoattribute:: Hub.loop

Creating fibers and switching
-----------------------------

To create a new fiber, instantiate the :class:`Fiber` class and pass it a main
function. The :class:`Fiber` class is a thin wrapper on top of
:class:`fibers.Fiber`, to which it adds a few behaviors:

* The fiber is created as a child of the hub.
* Only the hub is allowed to switch to this fiber. This prevent complex
  interactions where any fiber can switch to any other fiber. In other words,
  the hub is a real *hub*.

.. autoclass:: gruvi.Fiber
    :members:

The only two fibers in a Gruvi program that use :class:`fibers.Fiber` directly
are the hub and the root fiber. All other fibers should be created as instances
of :class:`Fiber`.

When a fiber is created it doesn't run yet. To switch to the fiber, call its
:meth:`~Fiber.start` method and switch to the hub::

  def say_hello():
      print('Hello, there!')

  fiber = Fiber(say_hello)
  fiber.start()

  print('Starting fiber')
  get_hub().switch()
  print('Back in root fiber')

The output of this will be::

  Starting fiber
  Hello, there!
  Back in root fiber

Working with the event loop
---------------------------

To register interest in a certain event, you need to create the appropriate
:class:`pyuv.Handle` instance and add it to the loop. The callback to the
handle should cause a switch back to the current fiber. You also want to make
sure you implement a timeout on the event, and that you clean up the handle in
case it times out. Because this logic can be relatively tricky to get right,
Gruvi provides the :class:`switch_back` context manager for this:

.. autoclass:: switch_back
    :members:

Lockless operation and switchpoints
-----------------------------------

Functions that may cause a switch to happen are called *switch points*. In
Gruvi these functions are marked by a special decorator:

.. autofunction:: gruvi.switchpoint

Knowing where switches may happen is important if you need to modify global
state in a non-atomic way. If you can be sure that during the modification no
switch points are called, then you don't need any locks. This lockless
operation is one of the main benefits of green threads. Gruvi offers a context
manager that can help with this:

.. autoclass:: assert_no_switchpoints

The :class:`assert_no_switchpoints` context manager should not be overused.
Instead it is recommended to try and confine non-atomic changes to a global
state to single functions.

Utility functions
-----------------

.. autofunction:: gruvi.current_fiber

.. autofunction:: gruvi.spawn

.. autofunction:: gruvi.sleep

Fiber local data
----------------

.. autoclass:: gruvi.local

Hub reference
-------------

.. autoclass:: Hub
    :members:

Mixing threads and fibers
-------------------------

There are two common situations where you might want to mix threads and fibers:

* When running CPU intensive code. In this case, you should run the code the
  :func:`CPU thread pool <get_cpu_pool>`.

* When running third party code that performs blocking IO. In this case, run
  the code in the :func:`IO thread pool <get_io_pool>`.

In both cases, running the code in a thread pool allows the hub to continue
servicing IO for fibers. All other cases of mixing threads and fibers are
generally a bad idea.

The following code is Gruvi is thread safe:

* The :meth:`Hub.run_callback` method.
* All synchronization primitives in :ref:`sync-primitives`.

All other code is **not** thread safe. If, for whatever reason, you must access
this code from multiple threads, use locks to mediate access.

.. _python-fibers: https://github.com/saghul/python-fibers
.. _libuv: https://github.com/joyent/libuv
.. _pyuv: https://pypi.python.org/pypi/pyuv
.. _`Global Interpreter Lock`: https://wiki.python.org/moin/GlobalInterpreterLock
