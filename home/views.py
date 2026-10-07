from django.contrib import messages
from django.shortcuts import redirect, render as _render

from . import sample_data as datos


def _buscar(lista, id):
    return next((item for item in lista if item.id == id), None)


def render(request, template, contexto=None):
    comun = {'categorias': datos.CATEGORIAS, 'recientes': datos.PUBLICADAS[:3]}
    return _render(request, template, {**comun, **(contexto or {})})


# Sitio público

def index(request):
    return render(request, 'home/index.html', {
        'destacadas': [datos.PUBLICADAS[2], datos.PUBLICADAS[1], datos.PUBLICADAS[3]],
        'publicaciones': datos.PUBLICADAS,
    })


def noticia(request, id=None):
    publicacion = _buscar(datos.PUBLICADAS, id) if id else datos.PUBLICADAS[0]
    publicacion = publicacion or datos.PUBLICADAS[0]
    return render(request, 'home/noticia.html', {
        'publicacion': publicacion,
        'comentarios': [c for c in datos.COMENTARIOS
                        if c.publicacion.id == publicacion.id and c.estado == 'aprobado'],
        'galeria': [n.imagen for n in datos.PUBLICADAS if n.id != publicacion.id][:3],
        'otras': [n for n in datos.PUBLICADAS if n.id != publicacion.id][:4],
    })


def categoria(request):
    seleccion = _buscar(datos.CATEGORIAS, int(request.GET.get('id', 1) or 1))
    return render(request, 'home/categoria.html', {
        'categoria_actual': seleccion,
        'publicaciones': [n for n in datos.PUBLICADAS if seleccion and n.categoria.id == seleccion.id],
    })


def contactanos(request):
    if request.method == 'POST':
        messages.success(request, '¡Gracias por escribirnos! Te responderemos pronto.')
        return redirect('home:contactanos')
    return render(request, 'home/contactanos.html')


def login(request):
    return render(request, 'home/login.html')


def sign_up(request):
    return render(request, 'home/sign_up.html')


# Panel de administración

def perfil(request):
    return render(request, 'home/perfil.html', {'perfil_usuario': datos.PERFIL})


def crud_perfil(request):
    return render(request, 'home/crud_perfil.html', {'perfil_usuario': datos.PERFIL})


def crud_cambiar_contrasena(request):
    return render(request, 'home/crud_cambiar_contrasena.html')


def crud_noticias(request):
    return render(request, 'home/crud_noticias.html', {'publicaciones': datos.NOTICIAS})


def crear_publicacion(request, id=None):
    return render(request, 'home/crear_publicacion.html', {
        'publicacion': _buscar(datos.NOTICIAS, id) if id else None,
    })


def crud_comentarios(request):
    return render(request, 'home/crud_comentarios.html', {'comentarios': datos.COMENTARIOS})


def crud_categorias(request):
    return render(request, 'home/crud_categorias.html', {'categorias': datos.CATEGORIAS})


def editar_categoria(request, id):
    return render(request, 'home/editar_categoria.html', {
        'categoria': _buscar(datos.CATEGORIAS, id),
    })


def crud_usuarios(request):
    return render(request, 'home/crud_usuarios.html', {'usuarios': datos.USUARIOS})


def crear_usuario(request, id=None):
    return render(request, 'home/crear_usuario.html', {
        'usuario_editado': _buscar(datos.USUARIOS, id) if id else None,
        'perfil_editado': datos.PERFIL if id else None,
    })


def accion_pendiente(request, id, destino):
    messages.info(request, 'Esta acción se conectará a la base de datos en los siguientes laboratorios.')
    return redirect(destino)
