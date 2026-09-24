from django.db import migrations, models


def assert_no_customer_data(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    ProductSourceRow = apps.get_model('imports', 'ProductSourceRow')
    ProductSourceRejectedRow = apps.get_model('imports', 'ProductSourceRejectedRow')
    ExternalDataFile = apps.get_model('imports', 'ExternalDataFile')
    if Product.objects.exclude(customer_code='').exists():
        raise RuntimeError('Products with CUSTOMER assignments require explicit review before changing identity.')
    if ProductSourceRow.objects.exclude(customer_code='').exists() or ProductSourceRejectedRow.objects.exclude(customer_code='').exists():
        raise RuntimeError('CUSTOMER staging rows require explicit review before changing identity.')
    if ExternalDataFile.objects.filter(file_type='PRODUCTS', validation_summary__customer_column=True).exists():
        raise RuntimeError('A validated CUSTOMER source requires explicit review before changing identity.')


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0002_remove_product_products_pr_client__abaa70_idx_and_more'),
        ('imports', '0015_productsourcerejectedrow_customer_code_and_more'),
    ]

    operations = [
        migrations.RunPython(assert_no_customer_data, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name='product', name='products_pr_client__3d6b16_idx'),
        migrations.AlterUniqueTogether(name='product', unique_together=set()),
        migrations.RemoveField(model_name='product', name='customer_code'),
        migrations.AlterUniqueTogether(name='product', unique_together={('client', 'sku')}),
        migrations.AddIndex(model_name='product', index=models.Index(fields=['client', 'sku'], name='products_pr_client__abaa70_idx')),
    ]
