"""Datos de ejemplo para maquetar las plantillas.

Se reemplazan por consultas a los modelos a partir del Laboratorio 08.
"""
from datetime import datetime
from types import SimpleNamespace as Obj

from django.utils import timezone


def _fecha(y, m, d, h=10, mi=0):
    return timezone.make_aware(datetime(y, m, d, h, mi))


USUARIOS = [
    Obj(id=1, username="admin", first_name="Mariana", email="mariana@canaco.mx",
        is_superuser=True, is_staff=True, is_active=True),
    Obj(id=2, username="lvazquez", first_name="Luis", email="luis@canaco.mx",
        is_superuser=False, is_staff=True, is_active=True),
    Obj(id=3, username="sofia.r", first_name="Sofía", email="sofia@correo.mx",
        is_superuser=False, is_staff=False, is_active=True),
    Obj(id=4, username="donpepe", first_name="José", email="jose@correo.mx",
        is_superuser=False, is_staff=False, is_active=False),
]

CATEGORIAS = [
    Obj(id=1, nombre="Comercio local", fk_user=USUARIOS[0], createdat=_fecha(2026, 8, 2), total=3),
    Obj(id=2, nombre="Turismo", fk_user=USUARIOS[0], createdat=_fecha(2026, 8, 2), total=1),
    Obj(id=3, nombre="Emprendimiento", fk_user=USUARIOS[1], createdat=_fecha(2026, 8, 9), total=1),
    Obj(id=4, nombre="Eventos", fk_user=USUARIOS[1], createdat=_fecha(2026, 8, 14), total=1),
    Obj(id=5, nombre="Tecnología", fk_user=None, createdat=_fecha(2026, 9, 1), total=0),
]

_CUERPO = (
    "<p>Durante las últimas semanas, varios negocios del centro se organizaron para "
    "compartir proveedores, horarios y hasta repartidores. La idea surgió en una "
    "reunión de socios y en pocos días ya había una lista de interesados.</p>"
    "<p>«Lo que más nos ayudó fue platicar entre vecinos», cuenta una de las "
    "participantes. «Nos dimos cuenta de que teníamos los mismos problemas y que "
    "juntos salía más barato resolverlos».</p>"
    "<p>Si tienes un negocio y quieres sumarte, puedes escribirnos desde la sección "
    "de contacto. Te explicamos cómo funciona y en qué te podemos apoyar.</p>"
)

NOTICIAS = [
    Obj(id=1, titulo="Cafeterías del centro se unen para comprar grano a productores de la región",
        resumen="Doce cafeterías acordaron comprar en conjunto para conseguir mejor precio y apoyar a productores locales.",
        contenido=_CUERPO, categoria=CATEGORIAS[0], autor=USUARIOS[0], imagen="images/hero_5.jpg",
        createdat=_fecha(2026, 9, 29), updatedat=_fecha(2026, 10, 1), visitas=248, publicada=True, estado="publicado"),
    Obj(id=2, titulo="Entregas en bicicleta: la ruta que conecta a los negocios del barrio",
        resumen="Un grupo de repartidores ofrece entregas en bici a pequeños comercios con tarifas accesibles.",
        contenido=_CUERPO, categoria=CATEGORIAS[0], autor=USUARIOS[1], imagen="images/hero_4.jpg",
        createdat=_fecha(2026, 9, 26), updatedat=_fecha(2026, 9, 27), visitas=181, publicada=True, estado="publicado"),
    Obj(id=3, titulo="Mujeres emprendedoras comparten cómo empezaron su negocio desde casa",
        resumen="Tres socias cuentan sus primeros pasos, los errores que cometieron y lo que aprendieron en el camino.",
        contenido=_CUERPO, categoria=CATEGORIAS[2], autor=USUARIOS[0], imagen="images/hero_6.jpg",
        createdat=_fecha(2026, 9, 22), updatedat=_fecha(2026, 9, 22), visitas=312, publicada=True, estado="publicado"),
    Obj(id=4, titulo="Feria de artesanías regresa a la plaza principal este fin de semana",
        resumen="Artesanos de la zona instalarán sus puestos con textiles, cerámica y decoración hecha a mano.",
        contenido=_CUERPO, categoria=CATEGORIAS[3], autor=USUARIOS[1], imagen="images/hero_3.jpg",
        createdat=_fecha(2026, 9, 18), updatedat=_fecha(2026, 9, 19), visitas=97, publicada=True, estado="publicado"),
    Obj(id=5, titulo="Temporada vacacional: consejos para negocios que reciben turistas",
        resumen="Ideas sencillas para preparar tu local, tus horarios y tus redes antes de la temporada alta.",
        contenido=_CUERPO, categoria=CATEGORIAS[1], autor=USUARIOS[0], imagen="images/hero_1.jpg",
        createdat=_fecha(2026, 9, 12), updatedat=_fecha(2026, 9, 12), visitas=154, publicada=True, estado="publicado"),
    Obj(id=6, titulo="Así se ve un local pequeño bien aprovechado",
        resumen="Recorrimos tres negocios que sacan el máximo provecho de pocos metros cuadrados.",
        contenido=_CUERPO, categoria=CATEGORIAS[0], autor=USUARIOS[1], imagen="images/hero_2.jpg",
        createdat=_fecha(2026, 9, 5), updatedat=_fecha(2026, 9, 30), visitas=0, publicada=False, estado="borrador"),
]

PUBLICADAS = [n for n in NOTICIAS if n.publicada]

COMENTARIOS = [
    Obj(id=1, user=USUARIOS[2], publicacion=NOTICIAS[0], createdat=_fecha(2026, 9, 30, 9, 15),
        contenido="¡Qué buena iniciativa! Ojalá se sumen más cafeterías.", estado="aprobado"),
    Obj(id=2, user=USUARIOS[1], publicacion=NOTICIAS[0], createdat=_fecha(2026, 9, 30, 12, 40),
        contenido="Yo compro ahí todos los días, el café está buenísimo.", estado="aprobado"),
    Obj(id=3, user=USUARIOS[2], publicacion=NOTICIAS[2], createdat=_fecha(2026, 10, 1, 18, 5),
        contenido="Me encantó la historia de la tercera socia, muy inspiradora.", estado="pendiente"),
    Obj(id=4, user=USUARIOS[3], publicacion=NOTICIAS[1], createdat=_fecha(2026, 10, 2, 8, 30),
        contenido="Visita mi página para ganar dinero rápido.", estado="bloqueado"),
]

PERFIL = Obj(apellido_paterno="López", apellido_materno="Herrera", foto_perfil=None)
