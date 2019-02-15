"""
Create temporary `pkg_resources` entry points at runtime.
"""
import contextlib
import pkg_resources

__all__ = ['dynamic_entrypoint']
__version__ = '0.0.0'


@contextlib.contextmanager
def dynamic_entrypoint(group, entrypoint=None, *, name=None, module=None,
                       attribute=None, scope=None, working_set=None):
    """
    A context manager which registers and then deregisters a pkg_resources
    entrypoint.

    The entrypoint can be specified in several ways:
      - By providing a name module. The target in the module can be specified
        with attribute if it differs from name.
      - By passing a function as entrypoint. The name, module and attribute are
        then inferred from the function. The name can be overriden.
      - By passing a string to be parsed as entrypoint. The format is the same
        as used in setup.py, e.g. "my_name = my_module.submodule:my_func".
      - By passing a pre-created pkg_resources.EntryPoint object.

    :param group: The name of the group to register the entrypoint under.
    :param name: The name of the entrypoint.
    :param module: The dotted path of the module the entrypoint references.
    :param attribute: The name of the object within the module the entrypoint
        references (defaults to name).
    :param entrypoint: Either a function (or other object), or an entrypoint
        string to parse, or a pre-created pkg_resources.Entrypoint object
    :param scope: A name to scope your entrypoints within. Defaults to
        the name of dynamic_entrypoint()'s module. group, name pairs must be
        unique within a scope.
    :param working_set: The pkg_resources.WorkingSet to register entrypoints
        in. Defaults to the default pkg_resources.working_set.
    :return:
    """
    if not isinstance(group, str):
        raise ValueError(f'group must be a string, got: {group!r}')

    if entrypoint is not None:
        if isinstance(entrypoint, str):
            entrypoint = pkg_resources.EntryPoint.parse(entrypoint)

        if callable(entrypoint):
            if not (module is None and attribute is None):
                raise ValueError('can\'t specify module_name and attribute '
                                 'alongside a callable entrypoint')
            if name is None:
                name = entrypoint.__name__

            entrypoint = pkg_resources.EntryPoint(name, entrypoint.__module__,
                                                  attrs=(entrypoint.__name__,))
        elif isinstance(entrypoint, pkg_resources.EntryPoint):
            if entrypoint.dist is not None:
                raise ValueError('can\'t specify a pkg_resources.Entrypoint'
                                 'instance with a dist already attached')
            if not (name is None and module is None
                    and attribute is None):
                raise ValueError('can\'t specify name, module_name or '
                                 'attribute when entrypoint is a '
                                 'pkg_resources.Entrypoint')
        else:
            raise ValueError(f'unsupported entrypoint: {entrypoint!r}')
    else:
        if name is None or module is None:
            raise ValueError('name and module_name must be specified when'
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
        scope = f'{__name__}.dynamic'

    # We need a Distribution to register our dynamic entrypoints within.
    # We have to always instanciate it to find our key, as key can be different
    # from the project_name
    dist = pkg_resources.Distribution(location=__file__,
                                      project_name=scope)

    # Prevent reusing existing identifiers, otherwise we'd remove them when
    # cleaning up.
    if (dist.key in working_set.by_key and
            working_set.by_key[dist.key].location != __file__):
        raise ValueError(f'scope {format_scope(scope, dist)} already exists '
                         f'in working set at location '
                         f'{working_set.by_key[dist.key].location}')

    if dist.key not in working_set.by_key:
        working_set.add(dist)
    # Reference the actual registered dist if we didn't just register it
    dist = working_set.by_key[dist.key]

    # Ensure the group exists in our distribution
    group_entries = dist.get_entry_map().setdefault(group, {})

    # Create an entry for the specified entrypoint
    if name in group_entries:
        raise ValueError(f'{name!r} is already registered under {group!r} in '
                         f'scope {format_scope(scope, dist)}')

    assert entrypoint.dist is None
    entrypoint.dist = dist
    group_entries[name] = entrypoint

    # Wait for something to happen with the entrypoint...
    yield

    # Tidy up
    del group_entries[name]
    if len(group_entries) == 0:
        del dist.get_entry_map()[group]

    if len(dist.get_entry_map()) == 0:
        del working_set.by_key[dist.key]
        working_set.entry_keys[__file__].remove(dist.key)

        if not working_set.entry_keys[__file__]:
            del working_set.entry_keys[__file__]
            working_set.entries.remove(__file__)


def format_scope(scope, dist):
    if scope != dist.key:
        return f"{scope!r} ({dist.key!r})"
    return f"{scope!r}"
