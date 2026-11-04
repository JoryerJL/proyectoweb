from django.contrib import admin

from .models import Archivo, Categoria, Comentario, GaleriaPublicacion, MensajeContacto, Perfil, Publicacion


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'fk_user', 'createdat')
    search_fields = ('nombre',)
    raw_id_fields = ('fk_user',)
    readonly_fields = ('slug', 'createdat')


@admin.register(Archivo)
class ArchivoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'tamano', 'fk_user', 'createdat')
    list_filter = ('tipo',)
    search_fields = ('nombre', 'nombre_temporal')
    raw_id_fields = ('fk_user',)
    readonly_fields = ('createdat',)


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'apellido_paterno', 'apellido_materno', 'email_verificado')
    list_filter = ('email_verificado',)
    search_fields = ('user__username', 'apellido_paterno', 'apellido_materno')
    raw_id_fields = ('user', 'foto_perfil')


class GaleriaPublicacionInline(admin.TabularInline):
    model = GaleriaPublicacion
    extra = 0
    raw_id_fields = ('archivo',)
    readonly_fields = ('createdat',)


@admin.register(Publicacion)
class PublicacionAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'categoria', 'autor', 'estado', 'visitas', 'createdat')
    list_filter = ('estado', 'categoria', 'createdat')
    search_fields = ('titulo', 'resumen', 'autor__username')
    list_select_related = ('categoria', 'autor')
    raw_id_fields = ('autor', 'imagen_portada')
    readonly_fields = ('slug', 'createdat', 'updatedat', 'visitas')
    date_hierarchy = 'createdat'
    inlines = [GaleriaPublicacionInline]


@admin.register(GaleriaPublicacion)
class GaleriaPublicacionAdmin(admin.ModelAdmin):
    list_display = ('publicacion', 'archivo', 'createdat')
    raw_id_fields = ('publicacion', 'archivo')
    readonly_fields = ('createdat',)


@admin.register(Comentario)
class ComentarioAdmin(admin.ModelAdmin):
    list_display = ('publicacion', 'user', 'estado', 'createdat')
    list_filter = ('estado', 'createdat')
    search_fields = ('contenido', 'user__username', 'publicacion__titulo')
    list_select_related = ('publicacion', 'user')
    raw_id_fields = ('publicacion', 'user')
    readonly_fields = ('createdat', 'updatedat')


@admin.register(MensajeContacto)
class MensajeContactoAdmin(admin.ModelAdmin):
    list_display = ('asunto', 'nombre', 'email', 'atendido', 'created_at')
    list_filter = ('atendido', 'created_at')
    search_fields = ('nombre', 'email', 'asunto', 'mensaje')
    readonly_fields = ('created_at',)
