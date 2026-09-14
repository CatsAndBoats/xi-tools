"""``xi ability`` command group."""

import click

from xi.ability.xi_catalog import catalog_cmd
from xi.ability.xi_compose import compose_cmd, recipe_cmd
from xi.ability.xi_inspect import cmd as inspect_cmd
from xi.ability.xi_publish import publish_cmd


@click.group("ability")
def group():
    """Ability presentations — routine timelines of motion, VFX and sound."""


group.add_command(inspect_cmd, "inspect")
group.add_command(recipe_cmd, "recipe")
group.add_command(compose_cmd, "compose")
group.add_command(publish_cmd, "publish")
group.add_command(catalog_cmd, "catalog")
