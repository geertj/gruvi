***************************
Asynchronous function calls
***************************

Gruvi provides functionality to execute functions asynchronously outside the
current flow of control. The API is a *futures* based interface, modeled after
the :mod:`concurrent.futures` and :mod:`asyncio` packages in the Python
standard library.

.. currentmodule:: gruvi

.. autoclass:: gruvi.Future
    :members:

.. autoclass:: gruvi.PoolBase
    :members:

.. autoclass:: gruvi.FiberPool
    :show-inheritance:

.. autoclass:: gruvi.ThreadPool
    :show-inheritance:

.. autofunction:: gruvi.get_io_pool

.. autofunction:: gruvi.get_cpu_pool

.. autofunction:: gruvi.blocking

.. autofunction:: gruvi.wait

.. autofunction:: gruvi.as_completed
