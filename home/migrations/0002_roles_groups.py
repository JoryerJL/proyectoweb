from django.contrib.auth.management import create_permissions
from django.db import migrations

# Frozen on purpose: migrations must not import application code that may change.
CONTENT = ['publicacion', 'categoria']
ROLE_PERMISSIONS = {
    'Colaborador': [
        ('home', 'add_comentario'), ('home', 'view_comentario'), ('home', 'view_publicacion'),
    ],
    'Editor': [
        ('home', 'add_publicacion'), ('home', 'change_publicacion'),
        ('home', 'delete_publicacion'), ('home', 'view_publicacion'),
        ('home', 'add_categoria'), ('home', 'change_categoria'),
        ('home', 'delete_categoria'), ('home', 'view_categoria'),
        ('home', 'add_comentario'), ('home', 'change_comentario'),
        ('home', 'delete_comentario'), ('home', 'view_comentario'),
    ],
}
ROLE_PERMISSIONS['Administrador'] = ROLE_PERMISSIONS['Editor'] + [
    ('auth', 'add_user'), ('auth', 'change_user'), ('auth', 'delete_user'), ('auth', 'view_user'),
]


def ensure_permissions(apps):
    # Permissions are normally created post_migrate, which has not run yet on a fresh DB.
    for app_config in apps.get_app_configs():
        if app_config.label in ('home', 'auth'):
            app_config.models_module = True
            create_permissions(app_config, verbosity=0, apps=apps)
            app_config.models_module = None


def create_roles(apps, schema_editor):
    ensure_permissions(apps)
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    User = apps.get_model('auth', 'User')

    groups = {}
    for name, perms in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set([
            Permission.objects.get(content_type__app_label=app, codename=codename)
            for app, codename in perms
        ])
        groups[name] = group

    # Backfill from the legacy flags: superuser -> Administrador, staff -> Editor, rest -> Colaborador.
    for user in User.objects.all():
        if user.is_superuser:
            target = 'Administrador'
        elif user.is_staff:
            target = 'Editor'
        else:
            target = 'Colaborador'
        user.groups.add(groups[target])


def remove_roles(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name__in=list(ROLE_PERMISSIONS)).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('home', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(create_roles, remove_roles)]
