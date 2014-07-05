.. _sync-primitives:

==========================
Synchronization primitives
==========================

Gruvi contains a set of primitives that can be used for synchronization between
multiple fibers and threads. All primitives documented below are thread safe.
They are modeled after the primitives in the Python :mod:`threading` and
:mod:`queue` modules.

.. currentmodule:: gruvi

.. autoclass:: gruvi.Lock
    :members:
    :inherited-members:

.. autoclass:: gruvi.RLock
    :members:
    :inherited-members:

.. autoclass:: gruvi.Event
    :members:

.. autoclass:: gruvi.Condition
    :members:

.. autoexception:: gruvi.QueueEmpty

.. autoexception:: gruvi.QueueFull

.. autoclass:: gruvi.Queue
    :members:

.. autoclass:: gruvi.LifoQueue
    :members:

.. autoclass:: gruvi.PriorityQueue
    :members:
