import contextlib

import pkg_resources
import pytest

import prybar
from prybar import dynamic_entrypoint


@pytest.fixture(autouse=True)
def validate_entrypoint_cleanup():
    for key, dist in pkg_resources.working_set.by_key.items():
        if dist.location == prybar.__file__:
            pytest.fail(f'a dist created by prybar exists before running a '
                        f'test: key: {key}, dist: {dist}')
    if prybar.__file__ in pkg_resources.working_set.entries:
        pytest.fail('prybar.py in working_set.entries before running a test')

    yield

    for key, dist in pkg_resources.working_set.by_key.items():
        if dist.location == prybar.__file__:
            pytest.fail(f'a dist created by prybar exists after running a '
                        f'test: key: {key}, dist: {dist}')
    if prybar.__file__ in pkg_resources.working_set.entries:
        pytest.fail('prybar.py in working_set.entries after running a test')


class SomeClass:

    class Nested:
        def method(self):
            pass

    @staticmethod
    def func():
        pass

    @staticmethod
    def func_without_module(self):
        pass


SomeClass.func_without_module.__module__ = None


def ep_1():
    return 1


def ep_2():
    return 2


def ep_3():
    return 3


def test_dynamic_entrypoint_registers_entrypoint_via_with():
    assert list(pkg_resources.iter_entry_points('test-group')) == []

    with dynamic_entrypoint('test-group', ep_1):
        eps = list(pkg_resources.iter_entry_points('test-group'))
        assert len(eps) == 1
        assert eps[0].name == 'ep_1'
        assert eps[0].load() is ep_1

    assert list(pkg_resources.iter_entry_points('test-group')) == []


def test_dynamic_entrypoint_registers_entrypoint_via_decorator():
    assert list(pkg_resources.iter_entry_points('test-group')) == []

    @dynamic_entrypoint('test-group', ep_1)
    def func():
        eps = list(pkg_resources.iter_entry_points('test-group'))
        assert len(eps) == 1
        assert eps[0].name == 'ep_1'
        assert eps[0].load() is ep_1
    func()

    assert list(pkg_resources.iter_entry_points('test-group')) == []


@pytest.mark.parametrize('expected_args', [(), (1, 2, 3)])
@pytest.mark.parametrize('expected_kwargs', [{}, {'a': 1, 'b': 2}])
def test_decorator_maintains_arguments(expected_args, expected_kwargs):
    @dynamic_entrypoint('test-group', ep_1)
    def func(*args, **kwargs):
        assert args == expected_args
        assert kwargs == expected_kwargs

    func(*expected_args, **expected_kwargs)


def test_decorator_maintains_return_value():
    @dynamic_entrypoint('test-group', ep_1)
    def func():
        return 42

    assert func() == 42


def test_decorator_maintains_raised_exceptions():
    @dynamic_entrypoint('test-group', ep_1)
    def func():
        raise ValueError('foo')

    with pytest.raises(ValueError) as excinfo:
        func()
    assert str(excinfo.value) == 'foo'


def test_dynamic_entrypoint_registers_entrypoint_via_start():
    assert list(pkg_resources.iter_entry_points('test-group')) == []

    dep = dynamic_entrypoint('test-group', ep_1)
    dep.start()
    eps = list(pkg_resources.iter_entry_points('test-group'))
    assert len(eps) == 1
    assert eps[0].name == 'ep_1'
    assert eps[0].load() is ep_1
    dep.stop()

    assert list(pkg_resources.iter_entry_points('test-group')) == []


def test_entrypoint_can_be_entered_multiple_times():
    dyn_ep = dynamic_entrypoint('test-group', ep_1)

    def assert_ep_1_active():
        eps = list(pkg_resources.iter_entry_points('test-group'))
        assert len(eps) == 1
        assert eps[0].load() is ep_1

    @dyn_ep
    def func_with_ep_1_active():
        assert_ep_1_active()

        # we can enter the context manager again from a decorated function
        with dyn_ep:
            assert_ep_1_active()

        # It's still active now, even though this context manager has stopped
        assert_ep_1_active()

    # Nothing's used the entry point yet, so it doesn't exist
    assert list(pkg_resources.iter_entry_points('test-group')) == []

    with dyn_ep:
        assert_ep_1_active()

        # we can use a decorated function with entry point active
        func_with_ep_1_active()

        # we can enter the manager again
        with dyn_ep:
            assert_ep_1_active()

            # We can't use the manual API while a context manager is active
            with pytest.raises(RuntimeError):
                dyn_ep.stop()

            with pytest.raises(RuntimeError):
                dyn_ep.start()

        # and again, it's still active now
        assert_ep_1_active()

    # Now there are no more users, so it's gone
    assert list(pkg_resources.iter_entry_points('test-group')) == []

    # And we can re-activate it again:
    with dyn_ep:
        assert_ep_1_active()

    assert list(pkg_resources.iter_entry_points('test-group')) == []


def test_multiple_entrypoint_registration():
    names = ['ep_1', 'ep_2', 'ep_3']

    with contextlib.ExitStack() as stack:
        for name in ['ep_1', 'ep_2', 'ep_3']:
            stack.enter_context(dynamic_entrypoint('test-group',
                                                   entrypoint=globals()[name]))

        eps = list(pkg_resources.iter_entry_points('test-group'))
        assert [ep.name for ep in eps] == names


def test_names_must_be_unique_per_scope():
    with dynamic_entrypoint('test-group', name='foo', entrypoint=ep_1):
        with pytest.raises(ValueError) as excinfo:
            with dynamic_entrypoint('test-group', name='foo', entrypoint=ep_2):
                pytest.fail('must not enter')

    assert (str(excinfo.value) ==
            "'foo' is already registered under 'test-group' in scope "
            "'prybar.scope.default'")


def test_scope_cant_shadow_existing_distribution():
    with pytest.raises(ValueError) as excinfo:
        # Try to shadow pytest
        with dynamic_entrypoint('test-group', ep_1, scope='pytest'):
            pytest.fail('must not enter')

    assert str(excinfo.value).startswith(
        "scope 'pytest' already exists in working set at location /")


def test_names_need_not_be_unique_in_different_scopes():
    with dynamic_entrypoint('test-group', name='foo', entrypoint=ep_1,
                            scope='a'):
        with dynamic_entrypoint('test-group', name='foo', entrypoint=ep_2,
                                scope='b'):
            foos = list(pkg_resources.iter_entry_points('test-group', 'foo'))
            assert [ep.name for ep in foos] == ['foo', 'foo']
            assert [ep.load() for ep in foos] == [ep_1, ep_2]


@pytest.mark.parametrize('func_name', ['ep_1', 'ep_2', 'ep_3'])
def test_entrypoints_are_loadable(func_name):
    with dynamic_entrypoint('test-group', name=func_name, module=__name__):
        ep = next(pkg_resources.iter_entry_points('test-group'))

        assert ep.name == func_name
        assert ep.load() is globals()[func_name]


@pytest.mark.parametrize('kwargs, expected', [
    (dict(name='foo', module=__name__, attribute=('SomeClass', 'func')),
     SomeClass.func),
    (dict(name='foo', module=__name__, attribute=('SomeClass', 'Nested')),
     SomeClass.Nested),
    (dict(name='foo', module=__name__,
          attribute=('SomeClass', 'Nested', 'method')),
     SomeClass.Nested.method),
    (dict(name='foo', entrypoint=SomeClass.func), SomeClass.func),
    (dict(name='foo', entrypoint=SomeClass.Nested), SomeClass.Nested),
    (dict(name='foo', entrypoint=SomeClass.Nested.method),
     SomeClass.Nested.method),
])
def test_entrypoints_with_multiple_attributes_load_nested_objects(
        kwargs, expected):
    with dynamic_entrypoint('test-group', **kwargs):
        ep = next(pkg_resources.iter_entry_points('test-group'))

        assert ep.load() is expected


def test_callable_entrypoint_must_have_module_attr():
    assert SomeClass.func_without_module.__module__ is None

    with pytest.raises(ValueError) as excinfo:
        dynamic_entrypoint('test-group',
                           entrypoint=SomeClass.func_without_module)

    msg = str(excinfo.value)
    assert msg.startswith('callable entrypoint has no __module__: ')
    assert f'SomeClass.func_without_module' in msg


@pytest.mark.parametrize('args, kwargs', [
    # entrypoint as a function object
    (['test-group', ep_1], {}),
    # Use different name for entrypoint than function name
    (['test-group'], dict(name='ep_1', entrypoint=ep_2)),
    ([], dict(group='test-group', entrypoint=ep_1)),

    # Pre-created entrypoint
    (['test-group', pkg_resources.EntryPoint('ep_1', __name__,
                                             attrs=('ep_1',))], {}),
    # Entrypoint as a string to parse
    (['test-group', f'ep_1 = {__name__}:ep_1'], {}),

    # Names / paths to create entrypoint from
    (['test-group'], dict(name='ep_1', module=__name__)),
    (['test-group'], dict(name='ep_1', module=__name__, attribute='ep_1')),
    (['test-group'], dict(name='ep_1', module=__name__, attribute=('ep_1',))),
    (['test-group'], dict(name='ep_1', module=__name__, attribute=None)),
    (['test-group'], dict(name='ep_1', module=__name__, attribute=None))
])
def test_valid_arguments(args, kwargs):
    with dynamic_entrypoint(*args, **kwargs):
        assert ['ep_1'] == [ep.name for ep in
                            pkg_resources.iter_entry_points('test-group')]


@pytest.mark.parametrize('args, kwargs, exc, msg', [
    ([42], {}, TypeError,
     'group must be a string, got: 42'),

    (['test-group'], {}, TypeError,
     'name and module_name must be specified when entrypoint is not '
     'specified'),

    (['test-group', None], {}, TypeError,
     'name and module_name must be specified when entrypoint is not '
     'specified'),

    # EntryPoint instance with existing dist
    (['test-group', pkg_resources.EntryPoint('ep_1', __name__,
                                             attrs=('ep_1',), dist=object())],
     {}, ValueError, 'can\'t specify a pkg_resources.Entrypoint instance with '
                     'a dist already attached'),
    # Specifying things twice
    (['test-group', f'ep_1 = {__name__}:ep_1'], dict(name='abc'), TypeError,
     'can\'t specify name, module_name or attribute when entrypoint is a '
     'pkg_resources.Entrypoint'),
    (['test-group', f'ep_1 = {__name__}:ep_1'], dict(module='abc'), TypeError,
     'can\'t specify name, module_name or attribute when entrypoint is a '
     'pkg_resources.Entrypoint'),
    (['test-group', f'ep_1 = {__name__}:ep_1'], dict(attribute='abc'),
     TypeError, 'can\'t specify name, module_name or attribute when '
                'entrypoint is a pkg_resources.Entrypoint'),
])
def test_invalid_arguments(args, kwargs, exc, msg):
    with pytest.raises(exc) as excinfo:
        with dynamic_entrypoint(*args, **kwargs):
            pass

    assert msg in str(excinfo.value)


def test_cant_exit_without_enter():
    with pytest.raises(RuntimeError) as excinfo:
        dynamic_entrypoint('test-group', ep_1).__exit__(None, None, None)
    assert str(excinfo.value) == '__exit__() called more than __enter__()'


def test_cant_use_stop_with_context_manager():
    dep = dynamic_entrypoint('test-group', ep_1)
    with pytest.raises(RuntimeError) as excinfo:
        with dep:
            dep.stop()
    assert (str(excinfo.value) ==
            'can\'t stop() while active via __enter__()')


def test_cant_use_start_with_context_manager():
    dep = dynamic_entrypoint('test-group', ep_1)
    with pytest.raises(RuntimeError) as excinfo:
        with dep:
            dep.start()
    assert (str(excinfo.value) ==
            'can\'t start() while active via __enter__()')


def test_cant_use_stop_with_decorator():
    dep = dynamic_entrypoint('test-group', ep_1)

    @dep
    def block():
        with pytest.raises(RuntimeError) as excinfo:
            dep.stop()
        assert (str(excinfo.value) ==
                'can\'t stop() while active via __enter__()')
    block()


def test_cant_use_start_with_decorator():
    dep = dynamic_entrypoint('test-group', ep_1)

    @dep
    def block():
        with pytest.raises(RuntimeError) as excinfo:
            dep.start()
        assert (str(excinfo.value) ==
                'can\'t start() while active via __enter__()')
    block()


def test_cant_use_context_manager_with_start():
    dep = dynamic_entrypoint('test-group', ep_1)
    dep.start()

    with pytest.raises(RuntimeError) as excinfo:
        with dep:
            pytest.fail('should not enter block')
    dep.stop()

    assert str(excinfo.value) == 'can\'t __enter__() while active via start()'


def test_cant_use_decorator_with_start():
    dep = dynamic_entrypoint('test-group', ep_1)
    dep.start()

    @dep
    def foo():
        pytest.fail('should not enter function')

    with pytest.raises(RuntimeError) as excinfo:
        foo()
    dep.stop()

    assert str(excinfo.value) == 'can\'t __enter__() while active via start()'


def test_start_stop_can_be_called_when_already_started_or_stopped():
    dep = dynamic_entrypoint('test-group', ep_1)
    assert list(pkg_resources.iter_entry_points('test-group')) == []
    dep.stop()
    dep.stop()
    dep.start()
    assert len(list(pkg_resources.iter_entry_points('test-group'))) == 1
    dep.start()
    dep.start()
    assert len(list(pkg_resources.iter_entry_points('test-group'))) == 1
    dep.stop()
    dep.stop()
    assert list(pkg_resources.iter_entry_points('test-group')) == []


def test_scopes_are_normalised_by_pkg_resources():
    # scopes are pkg_resources distributions, and underscores are normalised
    # to hyphens in distribution names.
    with dynamic_entrypoint('test-group', entrypoint=ep_1, scope='foo-bar'):
        with pytest.raises(ValueError) as excinfo:
            with dynamic_entrypoint('test-group', entrypoint=ep_1,
                                    scope='foo_bar'):
                pass

    assert str(excinfo.value) == (
        "'ep_1' is already registered under 'test-group' in scope "
        "'foo_bar' ('foo-bar')")
