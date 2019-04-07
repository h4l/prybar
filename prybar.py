"""
Create temporary pkg_resources entry points at runtime.
"""
from contextlib import contextmanager
import pkg_resources
from typing import Union, Type, Callable, Optional
from functools import wraps

__all__ = ['dynamic_entrypoint']
__version__ = '1.0.0'


class DynamicEntrypoint:
    """The type of the context manager objects returned by
    :meth:`prybar.dynamic_entrypoint`.
    """

    def __init__(self, group: str, entrypoint: pkg_resources.EntryPoint,
                 working_set: pkg_resources.WorkingSet, scope: str):
        self.__group = group
        self.__entrypoint = entrypoint
        self.__working_set = working_set
        self.__scope = scope

        self.__active_via_start = False
        self.__active_count = 0
        self.__active_context_manager = None

    @property
    def group(self): return self.__group

    @property
    def entrypoint(self): return self.__entrypoint

    @property
    def working_set(self): return self.__working_set

    @property
    def scope(self): return self.__scope

    def __enter__(self):
        if self.__active_via_start:
            raise RuntimeError('can\'t __enter__() while active via start()')

        assert self.__active_count >= 0
        self.__active_count += 1

        if self.__active_count == 1:
            assert self.__active_context_manager is None
            self.__active_context_manager = self._create_context_manager(
                self.group, self.entrypoint, self.working_set, self.scope)
            self.__active_context_manager.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.__active_via_start:
            raise RuntimeError('can\'t __exit__() while active via start()')

        if self.__active_count < 1:
            raise RuntimeError('__exit__() called more than __enter__()')

        if self.__active_count == 1:
            assert self.__active_context_manager is not None
            self.__active_context_manager.__exit__(exc_type, exc_val, exc_tb)
            self.__active_context_manager = None

        self.__active_count -= 1

    def __call__(self, func: Callable):
        """
        Decorate a function to have this entry point enabled before it runs and
        removed afterwards.

        :param func: The function to decorate
        :return: The decorated function
        """
        @wraps(func)
        def with_dynamic_entrypoint(*args, **kwargs):
            with self:
                return func(*args, **kwargs)
        return with_dynamic_entrypoint

    def start(self):
        if self.__active_count > 0:
            raise RuntimeError('can\'t start() while active via __enter__()')

        if self.__active_via_start:
            return

        assert self.__active_context_manager is None
        self.__active_via_start = True
        self.__active_context_manager = self._create_context_manager(
            self.group, self.entrypoint, self.working_set, self.scope)
        self.__active_context_manager.__enter__()

    def stop(self):
        if self.__active_count > 0:
            raise RuntimeError('can\'t stop() while active via __enter__()')

        if not self.__active_via_start:
            return

        assert self.__active_context_manager is not None
        self.__active_context_manager.__exit__(None, None, None)
        self.__active_context_manager = None
        self.__active_via_start = False

    @staticmethod
    @contextmanager
    def _create_context_manager(group: str,
                                entrypoint: pkg_resources.EntryPoint,
                                working_set: pkg_resources.WorkingSet,
                                scope: str):
        name = entrypoint.name
        # We need a Distribution to register our dynamic entrypoints within.
        # We have to always instantiate it to find our key, as key can be
        # different from the project_name
        dist = pkg_resources.Distribution(location=__file__,
                                          project_name=scope)

        # Prevent creating entrypoints in distributions not created by us,
        # otherwise we could remove the distributions when cleaning up.
        if (dist.key in working_set.by_key and
                working_set.by_key[dist.key].location != __file__):
            raise ValueError(f'scope {format_scope(scope, dist)} already '
                             f'exists in working set at location '
                             f'{working_set.by_key[dist.key].location}')

        if dist.key not in working_set.by_key:
            working_set.add(dist)
        # Reference the actual registered dist if we didn't just register it
        dist = working_set.by_key[dist.key]

        # Ensure the group exists in our distribution
        group_entries = dist.get_entry_map().setdefault(group, {})

        # Create an entry for the specified entrypoint
        if name in group_entries:
            raise ValueError(f'{name!r} is already registered under {group!r} '
                             f'in scope {format_scope(scope, dist)}')

        assert entrypoint.dist is None
        entrypoint.dist = dist
        group_entries[name] = entrypoint

        # Wait for something to happen with the entrypoint...
        try:
            yield
        finally:
            # Tidy up
            del group_entries[name]
            # If we re-use this entrypoint (by re-entering the context) the
            # dist may well have changed (because it gets deleted from the
            # working set) so we shouldn't remember it.
            assert entrypoint.dist is dist
            entrypoint.dist = None
            if len(group_entries) == 0:
                del dist.get_entry_map()[group]

            if len(dist.get_entry_map()) == 0:
                del working_set.by_key[dist.key]
                working_set.entry_keys[__file__].remove(dist.key)

                if not working_set.entry_keys[__file__]:
                    del working_set.entry_keys[__file__]
                    working_set.entries.remove(__file__)


def dynamic_entrypoint(
        group: str,
        entrypoint: Optional[Union[Callable, Type[object], str,
                                   pkg_resources.EntryPoint]] = None, *,
        name: Optional[str] = None, module: Optional[str] = None,
        attribute: Optional[str] = None, scope: Optional[str] = None,
        working_set: Optional[pkg_resources.WorkingSet] = None
        ) -> DynamicEntrypoint:
    """
    :meth:`prybar.dynamic_entrypoint` registers and de-registers
    :mod:`pkg_resources` `entry points`_ at runtime.

    .. _entry points: https://setuptools.readthedocs.io/en/latest/pkg_resources.html#entry-points  # noqa: E501

    It acts as a context manager and function decorator. The entrypoint is
    registered within the ``with`` statement, or while the decorated function
    is running. It can also be registered and de-registered manually using
    its ``start()`` and ``stop()`` methods.

    The context manager/decorator is re-entrant, i.e. a single instance can be
    used in multiple with statements, or decorate multiple functions, and each
    usage site can be entered multiple times while the same or other usage
    sites are still in use. The entry point is registered once when the first
    with block or decorated function is entered, and remains registered until
    all with blocks/decorated functions have been left.

    In contrast, the ``start()``/``stop()`` API immediatley registers and
    deregisters the entry point. Calling ``start`` multiple times has no effect
    after the first, neither does calling ``stop``.

    Use of the ``start()``/``stop()`` API is incompatible with the context
    manager/decorator API. An error will be raised if an attempt is made
    to ``start()``/``stop()`` while a with block or decorated function is
    active, and vice versa.

    The ``group`` must always be provided as a string, but he entrypoint can
    be specified in several ways:

      - By providing a ``name`` and ``module``. The target in the module can be
        specified with ``attribute`` if it differs from ``name``.
      - By passing a function or class as ``entrypoint``. The ``name``,
        ``module`` and ``attribute`` are then inferred automatically. The
        ``name`` can be overriden.
      - By passing a string to be parsed as ``entrypoint``. The format is the
        same as used in setup.py, e.g.
        ``"my_name = my_module.submodule:my_func"``.
      - By passing a pre-created ``pkg_resources.EntryPoint`` object as
        ``entrypoint``.

    :param group: The name of the entrypoint group to register the entrypoint
        under. For example, ``myproject.plugins``.
    :param name: The name of the entrypoint.
    :param module: The dotted path of the module the entrypoint references.
    :param attribute: The name of the object within the module the entrypoint
        references (defaults to name).
    :param entrypoint: Either a function (or other object), or an entrypoint
        string to parse, or a pre-created pkg_resources.Entrypoint object
    :param scope: A name to scope your entrypoints within. ``group``, ``name``
        pairs must be unique within a scope, but multiple entrypoints with
        the same ``group`` and ``name`` can be created in different scopes. The
        scope defaults to ``prybar.scope.default`` if not specified.

        Note: internally this defines the name of the
        ``pkg_resources.Distribution`` that the entrypoint is registered under.
        If you specify a scope you should use your package's name as the prefix
        to avoid conflicts with entry points from other packages.
    :param working_set: The pkg_resources.WorkingSet to register entrypoints
        in. Defaults to the default pkg_resources.working_set.
    :return: The context manager/decorator —
        a :class:`prybar.DynamicEntrypoint`, which also supports ``start()``
        and ``stop()`` methods.
    """
    if not isinstance(group, str):
        raise TypeError(f'group must be a string, got: {group!r}')

    if entrypoint is not None:
        if isinstance(entrypoint, str):
            entrypoint = pkg_resources.EntryPoint.parse(entrypoint)

        if isinstance(entrypoint, pkg_resources.EntryPoint):
            if entrypoint.dist is not None:
                raise ValueError('can\'t specify a pkg_resources.Entrypoint '
                                 'instance with a dist already attached')
            if not (name is None and module is None
                    and attribute is None):
                raise TypeError('can\'t specify name, module_name or '
                                'attribute when entrypoint is a '
                                'pkg_resources.Entrypoint')
        elif hasattr(entrypoint, '__qualname__'):  # classes and functions
            if not (module is None and attribute is None):
                raise TypeError('can\'t specify module_name and attribute '
                                'alongside a callable entrypoint')
            if name is None:
                name = entrypoint.__name__

            attrs = tuple(entrypoint.__qualname__.split('.'))
            if '<locals>' in attrs:
                raise ValueError(f'callable entrypoint is not '
                                 f'importable: {entrypoint!r}')

            if getattr(entrypoint, '__module__', None) is None:
                raise ValueError(
                    f'callable entrypoint has no __module__: {entrypoint!r}')

            entrypoint = pkg_resources.EntryPoint(name, entrypoint.__module__,
                                                  attrs=attrs)
        else:
            raise TypeError(f'unsupported entrypoint: {entrypoint!r}')
    else:
        if name is None or module is None:
            raise TypeError('name and module_name must be specified when '
                            'entrypoint is not specified')

        if isinstance(attribute, str):
            attribute = (attribute,)
        if attribute is None:
            attribute = (name,)
        entrypoint = pkg_resources.EntryPoint(
            name, module, attrs=attribute)

    if working_set is None:
        working_set = pkg_resources.working_set
    if scope is None:
        scope = f'{__name__}.scope.default'

    return DynamicEntrypoint(group, entrypoint, working_set, scope)


def format_scope(scope, dist):
    if scope != dist.key:
        return f"{scope!r} ({dist.key!r})"
    return f"{scope!r}"
