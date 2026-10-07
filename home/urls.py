from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "home"

urlpatterns = [
    # Sitio público
    path("", views.index, name="index"),
    path("noticia/", views.noticia, name="noticia"),
    path("noticia/<int:id>/", views.noticia, name="noticia_detalle"),
    path("categoria/", views.categoria, name="categoria"),
    path("contactanos/", views.contactanos, name="contactanos"),
    path("login/", views.login, name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("sign_up/", views.sign_up, name="sign_up"),

    # Panel: perfil
    path("perfil/", views.perfil, name="perfil"),
    path("perfil/editar/", views.crud_perfil, name="crud_perfil"),
    path("perfil/contrasena/", views.crud_cambiar_contrasena, name="crud_cambiar_contrasena"),

    # Panel: noticias
    path("panel/noticias/", views.crud_noticias, name="crud_noticias"),
    path("panel/noticias/crear/", views.crear_publicacion, name="crear_publicacion"),
    path("panel/noticias/<int:id>/editar/", views.crear_publicacion, name="editar_publicacion"),
    path("panel/noticias/<int:id>/publicar/", views.accion_pendiente, {"destino": "home:crud_noticias"}, name="publicar_publicacion"),
    path("panel/noticias/<int:id>/eliminar/", views.accion_pendiente, {"destino": "home:crud_noticias"}, name="eliminar_publicacion"),

    # Panel: comentarios
    path("panel/comentarios/", views.crud_comentarios, name="crud_comentarios"),
    path("panel/comentarios/<int:id>/aprobar/", views.accion_pendiente, {"destino": "home:crud_comentarios"}, name="aprobar_comentario"),
    path("panel/comentarios/<int:id>/bloquear/", views.accion_pendiente, {"destino": "home:crud_comentarios"}, name="bloquear_comentario"),
    path("panel/comentarios/<int:id>/eliminar/", views.accion_pendiente, {"destino": "home:crud_comentarios"}, name="eliminar_comentario"),

    # Panel: categorías
    path("panel/categorias/", views.crud_categorias, name="crud_categorias"),
    path("panel/categorias/<int:id>/editar/", views.editar_categoria, name="editar_categoria"),
    path("panel/categorias/<int:id>/eliminar/", views.accion_pendiente, {"destino": "home:crud_categorias"}, name="eliminar_categoria"),

    # Panel: usuarios
    path("panel/usuarios/", views.crud_usuarios, name="crud_usuarios"),
    path("panel/usuarios/crear/", views.crear_usuario, name="crear_usuario"),
    path("panel/usuarios/<int:id>/editar/", views.crear_usuario, name="editar_usuario"),
    path("panel/usuarios/<int:id>/bloquear/", views.accion_pendiente, {"destino": "home:crud_usuarios"}, name="bloquear_usuario"),
    path("panel/usuarios/<int:id>/eliminar/", views.accion_pendiente, {"destino": "home:crud_usuarios"}, name="eliminar_usuario"),
]
