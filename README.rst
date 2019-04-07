prybar: Create temporary ``pkg_resources`` entry points at runtime
======================================================================

.. image:: https://travis-ci.org/h4l/prybar.svg?branch=master
    :target: https://travis-ci.org/h4l/prybar
    :alt: CI Status
.. image:: https://readthedocs.org/projects/prybar/badge/?version=latest
    :target: https://prybar.readthedocs.io/en/latest/
    :alt: Documentation Status
.. image:: https://img.shields.io/pypi/status/prybar.svg
    :target: https://pypi.org/project/prybar/
    :alt: PyPI - Status

A Python library to temporarily define ``pkg_resources`` `entry points <ep intro_>`_
at runtime. The primary use case is testing code which works with entry points.

.. _ep intro: https://packaging.python.org/guides/creating-and-discovering-plugins/#using-package-metadata

Installing
----------

.. code:: console

    $ pip install prybar

prybar requires Python 3.6 or greater.

Usage
-----

.. code:: pycon

    >>> import prybar
    >>> from pkg_resources import iter_entry_points
    >>> # Entry point doesn't exist
    >>> list(iter_entry_points('example.hash_types', 'sha256'))
    []
    >>> # With prybar's context manager we can create entry points temporarily
    >>> with prybar.dynamic_entrypoint('example.hash_types',
    ...                                name='sha256', module='hashlib'):
    ...     hash = next(iter_entry_points('example.hash_types', 'sha256')).load()
    ...     hash(b'foo').hexdigest()[:6]
    '2c26b4'
    >>> # And it's gone again
    >>> list(iter_entry_points('example.hash_types', 'sha256'))
    []

See the `full documentation <https://prybar.readthedocs.io/>`_ for more.
