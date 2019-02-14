from unittest.mock import patch
import contextlib
import functools
import pkg_resources

import pytest

from prybar import dynamic_entrypoint


nested_ep = None


def ep_1():
    return 1


def ep_2():
    return 2


def ep_3():
    return 3


@pytest.yield_fixture(name='nested_ep')
def create_nested_ep():
    with patch(f'{__name__}.nested_ep') as ep:
        yield ep


def test_dynamic_entrypoint_registers_entrypoint():
    assert list(pkg_resources.iter_entry_points('test-group')) == []

    with dynamic_entrypoint('test-group', ep_1):
        eps = list(pkg_resources.iter_entry_points('test-group'))
        assert len(eps) == 1
        assert eps[0].name == 'ep_1'


def test_dynamic_entrypoint_unregisters_entrypoint():
    with dynamic_entrypoint('test-group', ep_1):
        eps = list(pkg_resources.iter_entry_points('test-group'))
        assert len(eps) == 1
        assert eps[0].name == 'ep_1'

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
            "'prybar.dynamic'")


# TODO: test shadowing existing scope
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


@pytest.mark.parametrize('kwargs, expected_attr_path', [
    (dict(name='foo', module=__name__, attribute=('nested_ep', 'abc')),
     ('abc',)),
    (dict(name='foo', module=__name__, attribute=('nested_ep', 'abc', 'def')),
     ('abc', 'def')),
])
def test_entrypoints_with_multiple_attributes_load_nested_objects(
        kwargs, expected_attr_path, nested_ep):
    with dynamic_entrypoint('test-group', **kwargs):
        ep = next(pkg_resources.iter_entry_points('test-group'))
        loaded_ep = ep.load()

        expected_nested_ep = functools.reduce(getattr,
                                              expected_attr_path, nested_ep)

        assert loaded_ep is expected_nested_ep


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


@pytest.mark.parametrize('args, kwargs, exc', [
    (['test-group'], {}, ValueError),
    (['test-group', None], {}, ValueError),
    # EntryPoint instance with existing dist
    (['test-group', pkg_resources.EntryPoint('ep_1', __name__,
                                             attrs=('ep_1',), dist=object())],
     {}, ValueError),
    # Specifying things twice
    (['test-group', f'ep_1 = {__name__}:ep_1'], dict(name='abc'), ValueError),
    (['test-group', f'ep_1 = {__name__}:ep_1'], dict(module='abc'),
     ValueError),
    (['test-group', f'ep_1 = {__name__}:ep_1'], dict(attribute='abc'),
     ValueError),
])
def test_invalid_arguments(args, kwargs, exc):
    with pytest.raises(exc):
        with dynamic_entrypoint(*args, **kwargs):
            pass
