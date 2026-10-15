from django.db import migrations, models


def move_table_prices_to_restaurants(apps, schema_editor):
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    Table = apps.get_model('restaurants', 'Table')
    db_alias = schema_editor.connection.alias
    for restaurant in Restaurant.objects.using(db_alias).all().iterator():
        price = (
            Table.objects.using(db_alias)
            .filter(restaurant_id=restaurant.pk, cost_per_table__isnull=False)
            .order_by('cost_per_table')
            .values_list('cost_per_table', flat=True)
            .first()
        )
        if price is not None:
            Restaurant.objects.using(db_alias).filter(pk=restaurant.pk).update(
                cost_per_table=price,
            )


def restore_table_prices(apps, schema_editor):
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    Table = apps.get_model('restaurants', 'Table')
    db_alias = schema_editor.connection.alias
    for restaurant in Restaurant.objects.using(db_alias).filter(
            cost_per_table__isnull=False).iterator():
        Table.objects.using(db_alias).filter(
            restaurant_id=restaurant.pk,
            cost_per_table__isnull=True,
        ).update(cost_per_table=restaurant.cost_per_table)


class Migration(migrations.Migration):

    dependencies = [
        ('restaurants', '0014_table_cost_per_table'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='cost_per_table',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.RunPython(move_table_prices_to_restaurants, restore_table_prices),
        migrations.RemoveField(
            model_name='table',
            name='cost_per_table',
        ),
    ]
