from django.core.cache import cache
from django.db.models import Count, Q

from home import roles
from home.models import Categoria, Publicacion

SIDEBAR_CACHE_KEY = 'home:sidebar'
SIDEBAR_CACHE_TTL = 60  # seconds


def _load_sidebar():
    publicadas = Q(publicacion__estado=Publicacion.ESTADO_PUBLICADO)
    return {
        'global_categorias': list(
            Categoria.objects.annotate(total=Count('publicacion', filter=publicadas)).order_by('nombre')
        ),
        'global_recientes': list(
            Publicacion.objects.filter(estado=Publicacion.ESTADO_PUBLICADO)
            .select_related('imagen_portada').order_by('-createdat')[:3]
        ),
    }


def invalidate_sidebar_cache():
    cache.delete(SIDEBAR_CACHE_KEY)


def global_categorias(request):
    data = cache.get(SIDEBAR_CACHE_KEY)
    if data is None:
        data = _load_sidebar()
        cache.set(SIDEBAR_CACHE_KEY, data, SIDEBAR_CACHE_TTL)
    return data


def user_role(request):
    return {'user_role': roles.get_user_role(request.user)}
