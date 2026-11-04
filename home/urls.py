from django.contrib.auth import views as auth_views
from django.urls import path

from . import forms, views

app_name = "home"

urlpatterns = [
    # Health check (used by Docker healthcheck and CD smoke test)
    path("healthz/", views.healthz, name="healthz"),

    # Sitio público
    path("", views.index, name="index"),
    path("noticia/", views.noticia, name="noticia"),
    # Legacy pk URLs: permanent redirect to the slug URL (listed first, slugs are never all digits).
    path("noticia/<int:pk>/", views.noticia_por_pk, name="noticia_pk"),
    path("noticia/<slug:slug>/", views.noticia, name="noticia_detalle"),
    path("categoria/", views.categoria, name="categoria"),
    path("categoria/<int:pk>/", views.categoria_por_pk, name="categoria_pk"),
    path("categoria/<slug:slug>/", views.categoria, name="categoria_detalle"),
    path("contactanos/", views.contactanos, name="contactanos"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="home/login.html",
            authentication_form=forms.VerifiedAuthenticationForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="home:login"), name="logout"),
    path("sign_up/", views.sign_up, name="sign_up"),
    path("verificacion_enviada/", views.verificacion_enviada, name="verificacion_enviada"),
    path("verificar_email/<uidb64>/<token>/", views.verificar_email, name="verificar_email"),
    path("reenviar_verificacion/", views.reenviar_verificacion, name="reenviar_verificacion"),

    # Panel: perfil
    path("perfil/", views.perfil, name="perfil"),
    path("perfil/editar/", views.crud_perfil, name="crud_perfil"),
    path("perfil/contrasena/", views.crud_cambiar_contrasena, name="crud_cambiar_contrasena"),

    # Panel: noticias
    path("panel/noticias/", views.crud_noticias, name="crud_noticias"),
    path("panel/noticias/crear/", views.crear_publicacion, name="crear_publicacion"),
    path("panel/noticias/<int:pk>/editar/", views.editar_publicacion, name="editar_publicacion"),
    path("panel/noticias/<int:pk>/publicar/", views.publicar_publicacion, name="publicar_publicacion"),
    path("panel/noticias/<int:pk>/eliminar/", views.eliminar_publicacion, name="eliminar_publicacion"),

    # Panel: comentarios
    path("panel/comentarios/", views.crud_comentarios, name="crud_comentarios"),
    path("panel/comentarios/<int:pk>/aprobar/", views.aprobar_comentario, name="aprobar_comentario"),
    path("panel/comentarios/<int:pk>/bloquear/", views.bloquear_comentario, name="bloquear_comentario"),
    path("panel/comentarios/<int:pk>/eliminar/", views.eliminar_comentario, name="eliminar_comentario"),

    # Panel: categorías
    path("panel/categorias/", views.crud_categorias, name="crud_categorias"),
    path("panel/categorias/<int:pk>/editar/", views.editar_categoria, name="editar_categoria"),
    path("panel/categorias/<int:pk>/eliminar/", views.eliminar_categoria, name="eliminar_categoria"),

    # Panel: usuarios
    path("panel/usuarios/", views.crud_usuarios, name="crud_usuarios"),
    path("panel/usuarios/crear/", views.crear_usuario, name="crear_usuario"),
    path("panel/usuarios/<int:pk>/editar/", views.editar_usuario, name="editar_usuario"),
    path("panel/usuarios/<int:pk>/bloquear/", views.bloquear_usuario, name="bloquear_usuario"),
    path("panel/usuarios/<int:pk>/eliminar/", views.eliminar_usuario, name="eliminar_usuario"),
]
