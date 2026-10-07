# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Lectores:** socios, comerciantes y público de la comunidad de Canaco (Cámara Nacional de Comercio) que entran a leer noticias, filtrar por categoría y comentar.
- **Colaboradores / editores / administradores:** personal que inicia sesión para publicar noticias, moderar comentarios, gestionar categorías y cuentas de usuario.

## Product Purpose

Blog de noticias de Canaco construido en Django como proyecto del curso "Laboratorio de Desarrollo Web Django" (TecNM). Éxito: que el lector encuentre y lea noticias fácilmente, y que el equipo publique y modere sin fricción.

## Operating Context

El proyecto se construye por laboratorios (`docs/LABORATORIOS`). Los labs 3–7B definen settings, rutas, vistas y maquetas HTML; los labs 8–13 agregan modelos, autenticación, CRUDs y context processors sobre las mismas plantillas, rutas (`home:*`) y nombres de variables de contexto.

## Capabilities and Constraints

- Django 6.1, app `home`, proyecto `canaco`, idioma `es-MX`, zona `America/Mexico_City`.
- SQLite en desarrollo; configuración MySQL comentada para labs posteriores.
- Páginas públicas: inicio, noticia, categoría, login, registro, contáctanos.
- Panel: perfil, editar perfil, noticias (CRUD + editor Quill), comentarios, categorías, usuarios, cambiar contraseña.
- Roles: Administrador (superuser), Editor (staff), Colaborador.
- Comentarios con estados: pendiente, aprobado, bloqueado. Noticias: borrador / publicado, con visitas.
- Las plantillas deben conservar los bloques, parciales (`partials/base.html`, `partials/sidebar_base.html`) y nombres de rutas de los labs para que los labs posteriores encajen.

## Brand Commitments

- Nombre: **Canaco**.
- Pedido explícito del usuario: sitio amigable y comunitario, con tipografía redondeada.
- Estilo estándar de blog limpio con tarjetas redondeadas (elegido sobre conceptos temáticos).
- La paleta debe leerse como sitio de noticias: se rechazaron tonos café/terracota por parecer de cafetería.

## Evidence on Hand

- Fotografías de ejemplo del curso en `docs/LABORATORIOS/Laboratorio06/static/images` (hero, horizontales, cuadradas, personas).
- No hay noticias, socios, cifras ni testimonios reales: todo contenido de ejemplo es ilustrativo y se reemplaza con datos de la base en labs posteriores.

## Product Principles

1. Leer primero: la noticia y su categoría siempre se encuentran en segundos.
2. Cercanía: lenguaje en segunda persona, tono de vecino, nunca corporativo frío.
3. Panel sin miedo: acciones claras, estados visibles, confirmación en lo destructivo.
4. Fiel a los laboratorios: estructura y nombres compatibles con el curso.

## Accessibility & Inclusion

Contraste AA, navegación por teclado y foco visible; público general de todas las edades.
