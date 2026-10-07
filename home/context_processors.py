from django.db.models import Count, Q

from home.models import Categoria, Publicacion


def global_categorias(request):
    publicadas = Q(publicacion__estado=Publicacion.ESTADO_PUBLICADO)
    return {
        'global_categorias': Categoria.objects.annotate(total=Count('publicacion', filter=publicadas)).order_by('nombre'),
        'global_recientes': Publicacion.objects.filter(estado=Publicacion.ESTADO_PUBLICADO)
                                               .select_related('imagen_portada').order_by('-createdat')[:3],
    }
