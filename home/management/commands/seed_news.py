from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from home import roles
from home.models import Archivo, Categoria, Comentario, Publicacion

# Photos in static/images/news come from StockSnap.io (CC0, no attribution required).
CATEGORIAS = ['Comercio', 'Economía', 'Eventos', 'Capacitación', 'Turismo']

PUBLICACIONES = [
    {
        'titulo': 'CANACO lanza programa de digitalización para pequeños comercios',
        'categoria': 'Comercio',
        'portada': 'images/news/digitalizacion-portada.jpg',
        'galeria': ['images/news/digitalizacion-1.jpg', 'images/news/digitalizacion-2.jpg'],
        'dias': 1,
        'visitas': 342,
        'resumen': 'Más de 200 negocios locales podrán acceder a asesoría gratuita para vender en línea y aceptar pagos digitales.',
        'contenido': (
            'La Cámara Nacional de Comercio presentó un programa de acompañamiento para que los pequeños '
            'comercios de la región den el salto al comercio electrónico.\n\n'
            'Durante seis semanas, los participantes recibirán asesoría sobre catálogos en línea, '
            'terminales de pago, facturación electrónica y presencia en redes sociales.\n\n'
            'Las inscripciones permanecerán abiertas hasta fin de mes y el cupo es limitado.'
        ),
    },
    {
        'titulo': 'Ventas del Buen Fin superan expectativas en la región',
        'categoria': 'Economía',
        'portada': 'images/news/buen-fin-portada.jpg',
        'galeria': ['images/news/buen-fin-1.jpg', 'images/news/buen-fin-2.jpg'],
        'dias': 4,
        'visitas': 518,
        'resumen': 'Los comercios afiliados reportaron un incremento del 18% en ventas respecto al año anterior.',
        'contenido': (
            'De acuerdo con el sondeo realizado entre los socios, los sectores con mayor crecimiento '
            'fueron electrónica, ropa y calzado, y artículos para el hogar.\n\n'
            'El uso de pagos con tarjeta y transferencias creció de forma notable, lo que confirma '
            'la tendencia hacia los medios de pago digitales.'
        ),
    },
    {
        'titulo': 'Expo Emprende 2026 abre su convocatoria para expositores',
        'categoria': 'Eventos',
        'portada': 'images/news/expo-emprende-portada.jpg',
        'galeria': ['images/news/expo-emprende-1.jpg', 'images/news/expo-emprende-2.jpg'],
        'dias': 7,
        'visitas': 205,
        'resumen': 'El evento reunirá a más de 120 emprendedores locales durante tres días en el centro de convenciones.',
        'contenido': (
            'La feria contará con zona de exhibición, conferencias magistrales y ruedas de negocios '
            'con compradores nacionales.\n\n'
            'Los socios de la cámara tendrán un descuento preferencial en la renta de stands.'
        ),
    },
    {
        'titulo': 'Taller gratuito de finanzas para emprendedores',
        'categoria': 'Capacitación',
        'portada': 'images/news/taller-finanzas-portada.jpg',
        'galeria': ['images/news/taller-finanzas-1.jpg', 'images/news/taller-finanzas-2.jpg'],
        'dias': 10,
        'visitas': 127,
        'resumen': 'Aprende a separar finanzas personales y del negocio, controlar flujo de efectivo y planear impuestos.',
        'contenido': (
            'El taller se impartirá de manera presencial los sábados de este mes en las instalaciones de la cámara.\n\n'
            'Está dirigido a dueños de negocios con menos de tres años de operación y no requiere '
            'conocimientos previos de contabilidad.'
        ),
    },
    {
        'titulo': 'Temporada vacacional impulsa la ocupación hotelera',
        'categoria': 'Turismo',
        'portada': 'images/news/turismo-portada.jpg',
        'galeria': ['images/news/turismo-1.jpg', 'images/news/turismo-2.jpg'],
        'dias': 14,
        'visitas': 289,
        'resumen': 'La ocupación promedio alcanzó 82%, con efecto positivo en restaurantes y comercios del centro histórico.',
        'contenido': (
            'Prestadores de servicios turísticos coincidieron en que la derrama económica benefició '
            'especialmente a los negocios del primer cuadro de la ciudad.\n\n'
            'La cámara trabaja con autoridades locales en una campaña de promoción para la próxima temporada.'
        ),
    },
    {
        'titulo': 'Nuevas reglas de facturación electrónica: lo que debes saber',
        'categoria': 'Economía',
        'portada': 'images/news/facturacion-portada.jpg',
        'galeria': ['images/news/facturacion-1.jpg', 'images/news/facturacion-2.jpg'],
        'dias': 20,
        'visitas': 461,
        'resumen': 'Resumimos los cambios más relevantes para comercios y cómo prepararse antes de la fecha límite.',
        'contenido': (
            'Los cambios afectan principalmente la emisión de complementos de pago y la cancelación de comprobantes.\n\n'
            'La cámara ofrecerá sesiones de orientación sin costo para sus socios durante las próximas semanas.'
        ),
    },
    {
        'titulo': 'Reunión mensual de socios: agenda y temas',
        'categoria': 'Eventos',
        'portada': 'images/news/reunion-socios-portada.jpg',
        'dias': 0,
        'visitas': 0,
        'borrador': True,
        'resumen': 'Borrador con la agenda preliminar de la próxima reunión de socios.',
        'contenido': 'Agenda pendiente de confirmar con el consejo directivo.',
    },
]

COMENTARIOS = [
    ('CANACO lanza programa de digitalización para pequeños comercios', 'Excelente iniciativa, ya me inscribí.', Comentario.ESTADO_APROBADO),
    ('CANACO lanza programa de digitalización para pequeños comercios', '¿El programa incluye apoyo con la terminal de pago?', Comentario.ESTADO_APROBADO),
    ('Ventas del Buen Fin superan expectativas en la región', 'En nuestra tienda también notamos el aumento.', Comentario.ESTADO_APROBADO),
    ('Taller gratuito de finanzas para emprendedores', '¿Habrá versión en línea del taller?', Comentario.ESTADO_PENDIENTE),
]


class Command(BaseCommand):
    help = 'Seed sample categories, news and comments (idempotent).'

    @transaction.atomic
    def handle(self, *args, **options):
        autor = self._get_author()
        lector = self._get_user('lector_demo', first_name='Lector', last_name='Demo')

        categorias = {
            nombre: Categoria.objects.get_or_create(nombre=nombre, defaults={'fk_user': autor})[0]
            for nombre in CATEGORIAS
        }

        now = timezone.now()
        creadas = 0
        for data in PUBLICACIONES:
            portada = self._get_image(data['portada'], autor)
            publicacion, created = Publicacion.objects.get_or_create(
                titulo=data['titulo'],
                defaults={
                    'resumen': data['resumen'],
                    'contenido': data['contenido'],
                    'categoria': categorias[data['categoria']],
                    'autor': autor,
                    'imagen_portada': portada,
                    'visitas': data['visitas'],
                    'estado': Publicacion.ESTADO_BORRADOR if data.get('borrador') else Publicacion.ESTADO_PUBLICADO,
                },
            )
            if created:
                creadas += 1
                # createdat is auto_now_add, so backdate it with an update to spread the timeline.
                Publicacion.objects.filter(pk=publicacion.pk).update(createdat=now - timedelta(days=data['dias']))
            elif publicacion.imagen_portada_id != portada.pk:
                publicacion.imagen_portada = portada
                publicacion.save(update_fields=['imagen_portada'])

            # Keep the gallery of seeded news in sync with PUBLICACIONES on every run.
            galeria = [self._get_image(ruta, autor) for ruta in data.get('galeria', [])]
            publicacion.galeria.exclude(archivo__in=galeria).delete()
            for archivo in galeria:
                publicacion.galeria.get_or_create(archivo=archivo)

        for titulo, contenido, estado in COMENTARIOS:
            Comentario.objects.get_or_create(
                publicacion=Publicacion.objects.get(titulo=titulo),
                user=lector,
                contenido=contenido,
                defaults={'estado': estado},
            )

        if options['verbosity']:
            self.stdout.write(self.style.SUCCESS(
                f'Seed done: {len(categorias)} categories, {creadas} new publications, '
                f'{Publicacion.objects.count()} total.'
            ))

    def _get_image(self, ruta, autor):
        nombre = ruta.rsplit('/', 1)[-1]
        archivo, _ = Archivo.objects.get_or_create(
            ruta=ruta,
            defaults={'nombre': nombre, 'nombre_temporal': nombre, 'tipo': 'image/jpeg', 'fk_user': autor},
        )
        return archivo

    def _get_author(self):
        return (
            User.objects.filter(is_superuser=True).order_by('date_joined').first()
            or self._get_user('editor_demo', first_name='Editor', last_name='Demo', is_staff=True)
        )

    def _get_user(self, username, **fields):
        user, created = User.objects.get_or_create(username=username, defaults=fields)
        if created:
            user.set_unusable_password()
            user.save(update_fields=['password'])
            roles.assign_role(user, roles.EDITOR if user.is_staff else roles.COLABORADOR)
        return user
