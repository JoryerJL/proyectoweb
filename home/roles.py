"""Single source of truth for user roles.

Roles are backed by ``django.contrib.auth.Group``. The groups and their
permissions are created by the data migration ``0002_roles_groups``.
Application code should authorize through permissions (``perm_required``,
``perms`` in templates) and use this module only to read or assign roles.
"""
from collections import namedtuple
from functools import wraps

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib.auth.views import redirect_to_login

Role = namedtuple('Role', ['value', 'label', 'description'])

COLABORADOR = 'colaborador'
EDITOR = 'editor'
ADMINISTRADOR = 'administrador'

ROLES = (
    Role(COLABORADOR, 'Colaborador', 'comenta noticias'),
    Role(EDITOR, 'Editor', 'publica y modera'),
    Role(ADMINISTRADOR, 'Administrador', 'acceso total'),
)
DEFAULT_ROLE = COLABORADOR

_BY_VALUE = {role.value: role for role in ROLES}
# Highest privilege first, so a user in several groups gets the strongest role.
_PRIORITY = (ADMINISTRADOR, EDITOR, COLABORADOR)


def get_role(value):
    """Return the Role for ``value`` or None if it is not a valid role."""
    return _BY_VALUE.get(value)


def get_user_role(user):
    """Return the user's Role, or None for anonymous users."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return _BY_VALUE[ADMINISTRADOR]
    group_names = {group.name for group in user.groups.all()}
    for value in _PRIORITY:
        if _BY_VALUE[value].label in group_names:
            return _BY_VALUE[value]
    return _BY_VALUE[DEFAULT_ROLE]


def assign_role(user, value):
    """Make ``value`` the user's only role and persist the matching flags.

    ``is_staff`` stays True for editor and administrator so the Django admin
    keeps working; ``is_superuser`` is only set for the administrator.
    """
    role = get_role(value)
    if role is None:
        raise ValueError(f'Unknown role: {value!r}')
    group, _ = Group.objects.get_or_create(name=role.label)
    user.groups.remove(*Group.objects.filter(name__in=[r.label for r in ROLES]))
    user.groups.add(group)
    user.is_staff = role.value != COLABORADOR
    user.is_superuser = role.value == ADMINISTRADOR
    user.save(update_fields=['is_staff', 'is_superuser'])
    return role


def perm_required(*perms):
    """View decorator: anonymous -> login redirect, logged in without perms -> 403."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated or not user.is_active:
                return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL or 'home:login')
            if not user.has_perms(perms):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
