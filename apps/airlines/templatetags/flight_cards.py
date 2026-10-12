from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Look a key up in a dict, so a template can index a dict built in a view.

    Django templates cannot subscript a dict with a variable, so the badge and
    logo maps the results view builds (``{obj_id: {...}}``) are read through this.
    Returns None rather than raising, because an id missing from the map is an
    ordinary case (a card with no badges, an airline with no photo).
    """
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None