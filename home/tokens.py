from django.contrib.auth.tokens import PasswordResetTokenGenerator

from .models import Perfil


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Single-use token for confirming a sign-up email.

    The hash covers the verified flag, so the link stops working once it is used,
    and the email, so it stops working if the address changes. Expiry reuses
    ``PASSWORD_RESET_TIMEOUT``.
    """

    key_salt = 'home.tokens.EmailVerificationTokenGenerator'

    def _make_hash_value(self, user, timestamp):
        # Query instead of user.perfil: the cached reverse relation can be stale
        # (the post_save signal caches the profile it just created).
        verified = Perfil.objects.filter(user_id=user.pk).values_list('email_verificado', flat=True).first()
        return self._hash_value(user, timestamp, bool(verified))

    @staticmethod
    def _hash_value(user, timestamp, verified):
        return f'{user.pk}{timestamp}{user.email}{verified}'


class _IssuedWhileUnverifiedGenerator(EmailVerificationTokenGenerator):
    """Checks a token as if the profile were still unverified.

    Lets the view tell a genuine, already-used link apart from a tampered one.
    """

    def _make_hash_value(self, user, timestamp):
        return self._hash_value(user, timestamp, False)


email_verification_token = EmailVerificationTokenGenerator()
issued_while_unverified_token = _IssuedWhileUnverifiedGenerator()
