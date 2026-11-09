"""Pinned host bindings for the same public builder and official EP version."""
import copy
import platform
import sys

from .common import ROOT, read, require, sha
from .source_adapter import source_file

POLICY = 'configs/native_build_platforms_v3.json'


def host_binding(*, root=ROOT, system=None, machine=None):
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    key = system + '_' + machine
    value = read(root / POLICY)
    require(value['schema'] == 'national_idf.native_build_platform_policy.v1', 'NATIVE_BUILD_POLICY_SCHEMA')
    require(tuple(sys.version_info[:3]) == tuple(value['required_python_release']),
            'NATIVE_BUILD_PYTHON_VERSION_MISMATCH')
    require(key in value['hosts'], 'NATIVE_BUILD_HOST_UNSUPPORTED', key)
    return copy.deepcopy(value['hosts'][key])


def catalog_path(*, root=ROOT, system=None, machine=None):
    return host_binding(root=root, system=system, machine=machine)['catalog']


def engine_directory(*, root=ROOT):
    binding = host_binding(root=root)
    catalog = read(root / binding['catalog'])
    require(catalog['sources']['sdk'] == binding['sdk'], 'NATIVE_BUILD_SDK_CATALOG_CONFLICT')
    sdk = read(source_file(binding['sdk'], root))
    require(sdk['version'] == '3.11.0+241b8abb4d', 'NATIVE_BUILD_SDK_VERSION')
    directory = root / binding['engine_directory']
    require(all((directory / name).is_file() for name in ('energyplus','Energy+.schema.epJSON','Energy+.idd')),
            'NATIVE_BUILD_OFFICIAL_ENGINE_MISSING')
    return directory


def api_libraries(directory):
    return sorted({p.resolve() for pattern in ('libenergyplusapi*.dylib','libenergyplusapi*.so*')
                   for p in directory.glob(pattern) if p.is_file()})


def bind_fixture(fixture, *, root=ROOT):
    """Port runtime artifacts only;keep the IDF and portable schema exact."""
    from .reference_workflow import ref
    value = copy.deepcopy(fixture)
    directory = engine_directory(root=root)
    # Runtime dispatch recognizes the official entry name even when a release
    # implements it as a symlink to a versioned executable.
    require((directory / 'energyplus').resolve().is_relative_to(root.resolve()), 'NATIVE_BUILD_ENGINE_OUTSIDE_PROJECT')
    target = {'path':str((directory / 'energyplus').relative_to(root)),
              'sha256':sha(directory / 'energyplus')}
    require(sha(source_file(fixture['engine_schema'], root)) == sha(directory / 'Energy+.schema.epJSON'),
            'NATIVE_BUILD_PORTABLE_SCHEMA_DIFFERS')
    if target in fixture['official_engine_files']:
        return value
    files = [directory / 'energyplus',directory / 'Energy+.schema.epJSON',directory / 'Energy+.idd']
    files += sorted((directory / 'pyenergyplus').glob('*.py'))
    libraries = api_libraries(directory)
    require(libraries, 'NATIVE_BUILD_API_LIBRARY_MISSING')
    files += libraries
    value['official_engine_files'] = [target if p.name == 'energyplus' else ref(p,root) for p in files]
    require(value['model'] == fixture['model'] and value['engine_schema'] == fixture['engine_schema'],
            'NATIVE_BUILD_PORT_CHANGED_PHYSICAL_INPUT')
    return value
