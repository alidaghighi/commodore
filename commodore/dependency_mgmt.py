import collections

import os
from pathlib import Path as P

import click

from . import git
from .helpers import yaml_load


Component = collections.namedtuple('Component', 'name repository_url target_directory')


def _relsymlink(srcdir, srcname, destdir, destname=None):
    if destname is None:
        destname = srcname
    # pathlib's relative_to() isn't suitable for this use case, since it only
    # works for dropping a path's prefix according to the documentation. See
    # https://docs.python.org/3/library/pathlib.html#pathlib.PurePath.relative_to
    link_src = os.path.relpath(P(srcdir) / srcname, start=destdir)
    link_dst = P(destdir) / destname
    try:
        if link_dst.exists():
            os.remove(link_dst)
        os.symlink(link_src, link_dst)
    except Exception as e:
        raise click.ClickException(f"While setting up symlinks: {e}") from e


def create_component_symlinks(cfg, component):
    target_directory = P('dependencies') / component
    _relsymlink(P(target_directory) / 'class', f"{component}.yml",
                'inventory/classes/components')
    component_defaults_class = P(target_directory) / 'class' / 'defaults.yml'
    if component_defaults_class.is_file():
        _relsymlink(P(target_directory) / 'class', 'defaults.yml',
                    P('inventory/classes/defaults'), destname=f"{component}.yml")
    else:
        click.secho('     > Old-style component detected. Please move ' +
                    'component defaults to \'class/defaults.yml\'', fg='yellow')
    libdir = P(target_directory) / 'lib'
    if libdir.is_dir():
        for file in os.listdir(libdir):
            if cfg.debug:
                click.echo(f"     > installing template library: {file}")
            _relsymlink(libdir, file, 'dependencies/lib')


def _discover_components(cfg, inventory_path):
    """
    Discover components in `inventory_path/`. Parse all classes found in
    inventory_path and look for class includes starting with `components.`.
    """
    components = set()
    inventory = P(inventory_path)
    for classfile in inventory.glob('**/*.yml'):
        if cfg.trace:
            click.echo(f" > Discovering components in {classfile}")
        classyaml = yaml_load(classfile)
        if classyaml is not None:
            for kls in classyaml.get('classes', []):
                if kls.startswith('components.'):
                    component = kls.split('.')[1]
                    if cfg.debug:
                        click.echo(f"   > Found component {component}")
                    components.add(component)
    return sorted(components)


def fetch_components(cfg):
    """
    Download all components required by target. Generate list of components
    by searching for classes with prefix `components.` in the inventory files.

    Component repos are searched in `GLOBAL_GIT_BASE/commodore_components`.
    """

    click.secho('Discovering components...', bold=True)
    component_names = _discover_components(cfg, 'inventory')
    components = _read_component_urls(cfg, component_names)
    click.secho('Fetching components...', bold=True)
    os.makedirs('inventory/classes/components', exist_ok=True)
    os.makedirs('inventory/classes/defaults', exist_ok=True)
    os.makedirs('dependencies/lib', exist_ok=True)
    for c in components:
        if cfg.debug:
            click.echo(f" > Fetching component {c.name}...")
        repo = git.clone_repository(c.repository_url, c.target_directory)
        cfg.register_component(c.name, repo)
        create_component_symlinks(cfg, c.name)


def _read_component_urls(cfg, component_names):
    components = []
    component_urls = {}
    if cfg.debug:
        click.echo(f"   > Read commodore config file {cfg.config_file}")
    try:
        commodore_config = yaml_load(cfg.config_file)
    except Exception as e:
        raise click.ClickException(f"Could not read Commodore configuration: {e}") from e
    if commodore_config is None:
        click.secho('Empty Commodore config file', fg='yellow')
    else:
        for component_override in commodore_config.get('components', []):
            if cfg.debug:
                click.echo(f"   > Found override for component {component_override['name']}:")
                click.echo(f"     Using URL {component_override['url']}")
            component_urls[component_override['name']] = component_override['url']
    for component_name in component_names:
        repository_url = \
            component_urls.get(
                component_name,
                f"{cfg.default_component_base}/{component_name}.git")
        target_directory = P('dependencies') / component_name
        component = Component(
            name=component_name,
            repository_url=repository_url,
            target_directory=target_directory)
        components.append(component)
    return components


def _set_component_version(cfg, component, version):
    click.echo(f" > {component}: {version}")
    try:
        git.checkout_version(cfg.get_component_repo(component), version)
    except git.RefError as e:
        click.secho(f"    unable to set version: {e}", fg='yellow')
    # Create symlinks again with correctly checked out components
    create_component_symlinks(cfg, component)
    cfg.set_component_version(component, version)


def set_component_versions(cfg, versions):
    """
    Set component versions according to versions provided in versions dict.
    The dict is assumed to contain component names as keys, and dicts as
    values. The value dicts are assumed to contain a key 'version' which
    indicates the version as a Git tree-ish.
    """

    click.secho('Setting component versions...', bold=True)
    for cn, c in versions.items():
        _set_component_version(cfg, cn, c['version'])


def fetch_jsonnet_libs(config, libs):
    """
    Download all libraries specified in list `libs`.
    Each entry in `libs` is assumed to be a dict with keys
      * 'repository', the value of which is interpreted as a git repository to
                      clone.
      * 'files', a list of dicts which defines which files in the repository
                 should be installed as template libraries.
    Each entry in files is assumed to have the keys
      * 'libfile', indicating a filename relative to the repository of the
                   library to install
      * 'targetfile', the file name to use as the symlink target when
                      installing the library
    """

    click.secho('Updating Jsonnet libraries...', bold=True)
    os.makedirs('dependencies/libs', exist_ok=True)
    os.makedirs('dependencies/lib', exist_ok=True)
    for lib in libs:
        libname = lib['name']
        filestext = ' '.join([f['targetfile'] for f in lib['files']])
        if config.debug:
            click.echo(f" > {libname}: {filestext}")
        repo = git.clone_repository(lib['repository'], P('dependencies/libs') / libname)
        for file in lib['files']:
            _relsymlink(repo.working_tree_dir, file['libfile'],
                        'dependencies/lib', destname=file['targetfile'])
