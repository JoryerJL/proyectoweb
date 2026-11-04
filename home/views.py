import logging
import os
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import InvalidPage, Paginator
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.db import connection
from django.db.models import F, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import urlencode
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from . import roles
from .emails import claim_send_slot, send_verification_email_async
from .forms import (
    IMAGE_EXTENSIONS,
    CategoriaForm,
    ComentarioForm,
    ContactoForm,
    PerfilForm,
    PublicacionForm,
    ResendVerificationForm,
    SignUpForm,
    UsuarioCreateForm,
    UsuarioEditForm,
    validate_image_upload,
)
from .models import Archivo, Categoria, Comentario, GaleriaPublicacion, Perfil, Publicacion
from .roles import perm_required
from .sanitize import clean_html
from .tokens import email_verification_token, issued_while_unverified_token

logger = logging.getLogger(__name__)


def guardar_archivo(upload, user):
    # The extension comes from the real image format, never from the client file name.
    extension = IMAGE_EXTENSIONS[validate_image_upload(upload)]
    nombre = (get_valid_filename(Path(upload.name).stem) or 'imagen') + extension
    filename = default_storage.save(f"uploads/{nombre}", upload)
    return Archivo.objects.create(
        nombre=nombre,
        nombre_temporal=filename,
        ruta=filename,
        tipo=upload.content_type,
        tamano=upload.size,
        fk_user=user,
    )


# Sitio público

def index(request):
    publicaciones = Publicacion.objects.filter(
        estado=Publicacion.ESTADO_PUBLICADO,
    ).select_related('categoria', 'autor', 'imagen_portada').order_by('-createdat')
    return render(request, 'home/index.html', {
        'slider': publicaciones[:3],
        'publicaciones': publicaciones[:3],
    })


def noticia_por_pk(request, pk):
    """Old ``/noticia/<pk>/`` links keep working: permanent redirect to the slug URL."""
    qs = Publicacion.objects.all()
    if not request.user.has_perm('home.change_publicacion'):
        qs = qs.filter(estado=Publicacion.ESTADO_PUBLICADO)
    return redirect(get_object_or_404(qs, pk=pk), permanent=True)


def categoria_por_pk(request, pk):
    return redirect(get_object_or_404(Categoria, pk=pk), permanent=True)


def noticia(request, slug=None):
    if slug and request.user.has_perm('home.change_publicacion'):
        qs = Publicacion.objects.all()
    else:
        qs = Publicacion.objects.filter(estado=Publicacion.ESTADO_PUBLICADO)

    qs = qs.select_related('categoria', 'autor', 'imagen_portada').prefetch_related(
        Prefetch('galeria', queryset=GaleriaPublicacion.objects.select_related('archivo').order_by('id')),
    )
    publicacion = get_object_or_404(qs, slug=slug) if slug else qs.order_by('-createdat').first()
    if not publicacion:
        messages.info(request, 'Todavía no hay noticias publicadas.')
        return redirect('home:index')

    Publicacion.objects.filter(pk=publicacion.pk).update(visitas=F('visitas') + 1)
    publicacion.visitas += 1

    if request.method == 'POST':
        if not request.user.is_authenticated:
            messages.error(request, 'Debes iniciar sesión para comentar.')
            return redirect('home:login')
        form = ComentarioForm(request.POST)
        if form.is_valid():
            Comentario.objects.create(
                publicacion=publicacion, user=request.user, contenido=form.cleaned_data['contenido'],
            )
            messages.success(request, 'Comentario enviado. Será visible cuando lo apruebe el administrador.')
        else:
            for error in form.errors['contenido']:
                messages.error(request, error)
        return redirect(publicacion)

    recientes = Publicacion.objects.filter(
        estado=Publicacion.ESTADO_PUBLICADO,
    ).exclude(pk=publicacion.pk).select_related('imagen_portada').order_by('-createdat')[:4]
    comentarios = publicacion.comentarios.filter(
        estado=Comentario.ESTADO_APROBADO,
    ).select_related('user').order_by('-createdat')

    return render(request, 'home/noticia.html', {
        'publicacion': publicacion,
        'recientes': recientes,
        'comentarios': list(comentarios),
    })


def is_partial_request(request):
    return request.headers.get('X-Requested-With') == 'fetch' or request.GET.get('partial') == '1'


def categoria(request, slug=None):
    categoria_actual = get_object_or_404(Categoria, slug=slug) if slug else None
    publicaciones = Publicacion.objects.filter(estado=Publicacion.ESTADO_PUBLICADO).select_related(
        'categoria', 'autor', 'imagen_portada',
    )
    if categoria_actual:
        publicaciones = publicaciones.filter(categoria=categoria_actual)
    busqueda = request.GET.get('q', '').strip()
    if busqueda:
        publicaciones = publicaciones.filter(Q(titulo__icontains=busqueda) | Q(resumen__icontains=busqueda))

    paginator = Paginator(publicaciones.order_by('-createdat', '-pk'), settings.NEWS_PAGE_SIZE)
    partial = is_partial_request(request)
    if partial:
        # Infinite scroll must never receive a clamped (repeated) page.
        try:
            page_obj = paginator.page(request.GET.get('page'))
        except InvalidPage:
            response = HttpResponse(status=204)
            response['X-Has-Next'] = 'false'
            patch_vary_headers(response, ['X-Requested-With'])
            return response
    else:
        page_obj = paginator.get_page(request.GET.get('page'))

    next_url = ''
    if page_obj.has_next():
        params = {'q': busqueda} if busqueda else {}
        params['page'] = page_obj.next_page_number()
        next_url = '?' + urlencode(params)

    context = {
        'categoria_actual': categoria_actual,
        'busqueda': busqueda,
        'page_obj': page_obj,
        'publicaciones': page_obj.object_list,
        'next_url': next_url,
    }
    if partial:
        # Next-page URL travels in the X-Next-Url header, not in the markup.
        response = render(request, 'home/partials/post_rows.html', context)
        response['X-Has-Next'] = 'true' if next_url else 'false'
        if next_url:
            response['X-Next-Url'] = next_url
        patch_vary_headers(response, ['X-Requested-With'])
        return response
    response = render(request, 'home/categoria.html', context)
    patch_vary_headers(response, ['X-Requested-With'])
    return response


def contactanos(request):
    form = ContactoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        mensaje = form.save()
        if settings.CONTACT_EMAIL:
            try:
                send_mail(
                    subject=f'[Contacto] {mensaje.asunto}',
                    message=f'De: {mensaje.nombre} <{mensaje.email}>\n\n{mensaje.mensaje}',
                    from_email=None,
                    recipient_list=[settings.CONTACT_EMAIL],
                    fail_silently=False,
                )
            except Exception:
                logger.warning('Could not send contact email for message %s', mensaje.pk, exc_info=True)
        messages.success(request, '¡Gracias por escribirnos! Te responderemos pronto.')
        return redirect('home:contactanos')
    return render(request, 'home/contactanos.html', {'form': form})


def sign_up(request):
    form = SignUpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        # Failures happen off-thread and are logged; the sent page offers the resend option.
        if claim_send_slot(user):
            send_verification_email_async(request, user)
        return redirect('home:verificacion_enviada')
    return render(request, 'home/sign_up.html', {'form': form})


def verificacion_enviada(request):
    return render(request, 'home/verificacion_enviada.html', {'form': ResendVerificationForm()})


def verificar_email(request, uidb64, token):
    try:
        user = User.objects.select_related('perfil').get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    perfil = getattr(user, 'perfil', None)
    if perfil is None:
        return render(request, 'home/verificacion_invalida.html', {'form': ResendVerificationForm()}, status=400)
    if perfil.email_verificado:
        # A genuine link used twice is not an error; tampered or foreign tokens still get a 400.
        if issued_while_unverified_token.check_token(user, token):
            messages.info(request, 'Tu correo ya estaba verificado. Inicia sesión.')
            return redirect('home:login')
        return render(request, 'home/verificacion_invalida.html', {'form': ResendVerificationForm()}, status=400)
    if not email_verification_token.check_token(user, token):
        return render(request, 'home/verificacion_invalida.html', {'form': ResendVerificationForm()}, status=400)
    perfil.email_verificado = True
    perfil.email_verificado_en = timezone.now()
    perfil.save(update_fields=['email_verificado', 'email_verificado_en'])
    messages.success(request, 'Tu correo fue confirmado. Ya puedes iniciar sesión.')
    return redirect('home:login')


def reenviar_verificacion(request):
    form = ResendVerificationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        # An unverified account wins over a verified duplicate (False sorts before True).
        user = (
            User.objects.select_related('perfil')
            .filter(email__iexact=form.cleaned_data['email'], is_active=True)
            .order_by('perfil__email_verificado')
            .first()
        )
        perfil = getattr(user, 'perfil', None)
        if perfil is not None and not perfil.email_verificado and claim_send_slot(user):
            send_verification_email_async(request, user)
        # Same response in every case so the form cannot be used to enumerate accounts.
        return render(request, 'home/reenviar_verificacion.html', {
            'form': ResendVerificationForm(),
            'sent': True,
        })
    return render(request, 'home/reenviar_verificacion.html', {'form': form})


# Panel: perfil

@login_required
def perfil(request):
    perfil_usuario, _ = Perfil.objects.get_or_create(user=request.user)
    return render(request, 'home/perfil.html', {'perfil_usuario': perfil_usuario})


@login_required
def crud_perfil(request):
    user = request.user
    perfil, _ = Perfil.objects.get_or_create(user=user)

    if request.method == 'POST':
        form = PerfilForm(request.POST, request.FILES, user=user)
        if form.is_valid():
            data = form.cleaned_data
            user.username = data['username']
            if data['email']:
                user.email = data['email']
            user.first_name = data['first_name']
            user.last_name = ' '.join(filter(None, [data['apellido_paterno'], data['apellido_materno']]))
            user.save()

            perfil.apellido_paterno = data['apellido_paterno']
            perfil.apellido_materno = data['apellido_materno']

            foto = data['foto']
            if foto:
                if perfil.foto_perfil:
                    archivo_anterior = perfil.foto_perfil
                    if archivo_anterior.ruta and hasattr(archivo_anterior.ruta, 'path') and os.path.exists(archivo_anterior.ruta.path):
                        os.remove(archivo_anterior.ruta.path)
                    archivo_anterior.delete()
                perfil.foto_perfil = guardar_archivo(foto, user)

            perfil.save()

            messages.success(request, 'Perfil actualizado correctamente.')
            return redirect('home:perfil')
        return render(request, 'home/crud_perfil.html', {'perfil_usuario': perfil, 'form': form})

    return render(request, 'home/crud_perfil.html', {'perfil_usuario': perfil})


@login_required
def crud_cambiar_contrasena(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Contraseña actualizada correctamente.')
        return redirect('home:crud_cambiar_contrasena')
    return render(request, 'home/crud_cambiar_contrasena.html', {'form': form})


# Panel: noticias

@perm_required('home.change_publicacion')
def crud_noticias(request):
    publicaciones = Publicacion.objects.select_related('categoria', 'autor').order_by('-createdat')
    return render(request, 'home/crud_noticias.html', {'publicaciones': publicaciones})


def _adjuntar_imagenes(publicacion, form, user):
    portada = form.cleaned_data.get('imagen_portada')
    if portada:
        publicacion.imagen_portada = guardar_archivo(portada, user)
        publicacion.save()
    for imagen in form.cleaned_data.get('galeria', []):
        GaleriaPublicacion.objects.create(publicacion=publicacion, archivo=guardar_archivo(imagen, user))


def _render_publicacion_form(request, form, publicacion=None):
    contenido = form['contenido'].value() or ''
    return render(request, 'home/crear_publicacion.html', {
        'form': form,
        'categorias': form.fields['categoria'].queryset,
        'publicacion': publicacion,
        # Re-sanitized because the editor renders it with |safe.
        'contenido_inicial': clean_html(contenido),
    })


@perm_required('home.add_publicacion')
def crear_publicacion(request):
    if request.method == 'POST':
        form = PublicacionForm(request.POST, request.FILES)
        if form.is_valid():
            publicacion = form.save(commit=False)
            publicacion.autor = request.user
            publicacion.save()
            _adjuntar_imagenes(publicacion, form, request.user)
            messages.success(request, 'Publicación creada correctamente.')
            return redirect('home:crud_noticias')
    else:
        form = PublicacionForm()
    return _render_publicacion_form(request, form)


@perm_required('home.change_publicacion')
def editar_publicacion(request, pk):
    publicacion = get_object_or_404(Publicacion, pk=pk)
    if request.method == 'POST':
        form = PublicacionForm(request.POST, request.FILES, instance=publicacion)
        if form.is_valid():
            publicacion = form.save()
            _adjuntar_imagenes(publicacion, form, request.user)
            messages.success(request, 'Publicación actualizada correctamente.')
            return redirect('home:crud_noticias')
    else:
        form = PublicacionForm(instance=publicacion)
    return _render_publicacion_form(request, form, publicacion)


@require_POST
@perm_required('home.change_publicacion')
def publicar_publicacion(request, pk):
    publicacion = get_object_or_404(Publicacion, pk=pk)
    publicacion.estado = Publicacion.ESTADO_PUBLICADO if publicacion.estado != Publicacion.ESTADO_PUBLICADO else Publicacion.ESTADO_BORRADOR
    publicacion.save()
    return redirect('home:crud_noticias')


@require_POST
@perm_required('home.delete_publicacion')
def eliminar_publicacion(request, pk):
    publicacion = get_object_or_404(Publicacion, pk=pk)
    publicacion.delete()
    messages.success(request, 'Publicación eliminada correctamente.')
    return redirect('home:crud_noticias')


# Panel: comentarios

@perm_required('home.change_comentario')
def crud_comentarios(request):
    comentarios = Comentario.objects.select_related('publicacion', 'user').order_by('-createdat')
    return render(request, 'home/crud_comentarios.html', {'comentarios': comentarios})


@require_POST
@perm_required('home.change_comentario')
def aprobar_comentario(request, pk):
    comentario = get_object_or_404(Comentario, pk=pk)
    comentario.estado = Comentario.ESTADO_APROBADO
    comentario.save()
    return redirect('home:crud_comentarios')


@require_POST
@perm_required('home.change_comentario')
def bloquear_comentario(request, pk):
    comentario = get_object_or_404(Comentario, pk=pk)
    comentario.estado = Comentario.ESTADO_BLOQUEADO
    comentario.save()
    return redirect('home:crud_comentarios')


@require_POST
@perm_required('home.delete_comentario')
def eliminar_comentario(request, pk):
    comentario = get_object_or_404(Comentario, pk=pk)
    comentario.delete()
    return redirect('home:crud_comentarios')


# Panel: categorías

@perm_required('home.change_categoria')
def crud_categorias(request):
    form = CategoriaForm()
    if request.method == 'POST':
        if not request.user.has_perm('home.add_categoria'):
            raise PermissionDenied
        form = CategoriaForm(request.POST)
        if form.is_valid():
            categoria = form.save(commit=False)
            categoria.fk_user = request.user
            categoria.save()
            messages.success(request, 'Categoría agregada correctamente.')
            return redirect('home:crud_categorias')
    categorias = Categoria.objects.all().order_by('-createdat')
    return render(request, 'home/crud_categorias.html', {'categorias': categorias, 'form': form})


@perm_required('home.change_categoria')
def editar_categoria(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        form = CategoriaForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoría actualizada correctamente.')
            return redirect('home:crud_categorias')
    else:
        form = CategoriaForm(instance=categoria)
    return render(request, 'home/editar_categoria.html', {'categoria': categoria, 'form': form})


@require_POST
@perm_required('home.delete_categoria')
def eliminar_categoria(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    categoria.delete()
    messages.success(request, 'Categoría eliminada correctamente.')
    return redirect('home:crud_categorias')


# Panel: usuarios

@perm_required('auth.view_user')
def crud_usuarios(request):
    def load():
        return list(User.objects.select_related('perfil').prefetch_related('groups').order_by('date_joined'))

    usuarios = load()
    # select_related caches a missing profile, so this check costs no extra queries.
    sin_perfil = [u for u in usuarios if not hasattr(u, 'perfil')]
    if sin_perfil:
        now = timezone.now()
        Perfil.objects.bulk_create([
            Perfil(user=u, email_verificado=True, email_verificado_en=now) for u in sin_perfil
        ])
        usuarios = load()
    for usuario in usuarios:
        usuario.rol = roles.get_user_role(usuario)
    return render(request, 'home/crud_usuarios.html', {'usuarios': usuarios})


@perm_required('auth.add_user')
def crear_usuario(request):
    form = UsuarioCreateForm(request.POST or None, initial={'rol': roles.DEFAULT_ROLE})
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Usuario creado correctamente.')
        return redirect('home:crud_usuarios')
    return render(request, 'home/crear_usuario.html', {
        'form': form,
        'roles': roles.ROLES,
        'rol_actual': form['rol'].value() or roles.DEFAULT_ROLE,
    })


@perm_required('auth.change_user')
def editar_usuario(request, pk):
    usuario = get_object_or_404(User, pk=pk)
    perfil, _ = Perfil.objects.get_or_create(user=usuario)
    rol_actual = roles.get_user_role(usuario).value
    initial = {
        'username': usuario.username,
        'email': usuario.email,
        'first_name': usuario.first_name,
        'apellido_paterno': perfil.apellido_paterno,
        'apellido_materno': perfil.apellido_materno,
        'rol': rol_actual,
    }
    form = UsuarioEditForm(request.POST or None, instance=usuario, initial=initial)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Usuario actualizado correctamente.')
        return redirect('home:crud_usuarios')
    return render(request, 'home/crear_usuario.html', {
        'form': form,
        'usuario_editado': usuario,
        'roles': roles.ROLES,
        'rol_actual': form['rol'].value() or rol_actual,
    })


@require_POST
@perm_required('auth.change_user')
def bloquear_usuario(request, pk):
    usuario = get_object_or_404(User, pk=pk)
    if usuario != request.user:
        usuario.is_active = not usuario.is_active
        usuario.save()
    return redirect('home:crud_usuarios')


@require_POST
@perm_required('auth.delete_user')
def eliminar_usuario(request, pk):
    usuario = get_object_or_404(User, pk=pk)
    if usuario != request.user:
        usuario.delete()
    return redirect('home:crud_usuarios')


def healthz(request):
    """Liveness/readiness probe: 200 when the database answers, 503 otherwise."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
    return JsonResponse({'status': 'ok'})
