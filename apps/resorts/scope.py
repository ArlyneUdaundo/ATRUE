from atrue_core.establishment_scope import EstablishmentScope


resort_scope = EstablishmentScope(
    establishment_type='RESORT',
    module='resorts',
    list_views={'manage'},
    platform_views=set(),
    id_resolvers={},
    allowed_attr='allowed_resort_ids',
    assignment_attr='assigned_resort_assignment',
    query_param='resort',
    entity_label='resort',
)
