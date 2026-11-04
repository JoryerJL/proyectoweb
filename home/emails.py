import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import Perfil
from .tokens import email_verification_token

logger = logging.getLogger(__name__)

SUBJECT = 'Confirma tu correo en Canaco'
RESEND_COOLDOWN_SECONDS = 60


def claim_send_slot(user):
    """Atomically reserve the right to send a verification email to ``user``.

    Returns True for exactly one caller per cooldown window, so concurrent requests cannot
    trigger a double send. The timestamp is written here, before any (possibly background) send.
    """
    now = timezone.now()
    cutoff = now - timedelta(seconds=RESEND_COOLDOWN_SECONDS)
    updated = (
        Perfil.objects.filter(user=user)
        .filter(Q(verificacion_enviada_en__isnull=True) | Q(verificacion_enviada_en__lt=cutoff))
        .update(verificacion_enviada_en=now)
    )
    return updated == 1


def _absolute_base(request_or_base):
    if isinstance(request_or_base, str):
        return request_or_base.rstrip('/')
    return request_or_base.build_absolute_uri('/').rstrip('/')


def send_verification_email(request_or_base, user):
    """Email ``user`` a single-use link to confirm their address.

    ``request_or_base`` is a request or an absolute base URL such as ``https://example.org``.
    Raises whatever the mail backend raises; callers decide how to degrade.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    url = _absolute_base(request_or_base) + reverse('home:verificar_email', args=[uid, token])
    context = {'user': user, 'verification_url': url, 'site_name': 'Canaco'}
    message = EmailMultiAlternatives(
        subject=SUBJECT,
        body=render_to_string('home/emails/verificar_email.txt', context),
        to=[user.email],
    )
    message.attach_alternative(render_to_string('home/emails/verificar_email.html', context), 'text/html')
    message.send(fail_silently=False)


def _deliver(base_url, user):
    try:
        send_verification_email(base_url, user)
    except Exception:
        logger.warning('Could not send verification email to user %s', user.pk, exc_info=True)


def send_verification_email_async(request_or_base, user):
    """Send the verification email without making the HTTP response wait for SMTP.

    The absolute base URL is captured here, before the thread starts: the request object must
    not be used from another thread. With ``EMAIL_SEND_ASYNC`` off (tests) it runs inline.
    Failures are logged, never raised.
    """
    base_url = _absolute_base(request_or_base)
    if not getattr(settings, 'EMAIL_SEND_ASYNC', True):
        _deliver(base_url, user)
        return
    threading.Thread(target=_deliver, args=(base_url, user), daemon=True).start()
