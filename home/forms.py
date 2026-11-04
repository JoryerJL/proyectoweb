"""Validated input for every view that used to read ``request.POST`` raw."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, BaseUserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from PIL import Image

from . import roles
from .models import Categoria, Comentario, MensajeContacto, Perfil, Publicacion

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
# Real image format (as detected by Pillow) -> file extension we store.
IMAGE_EXTENSIONS = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}

IMAGE_ERROR = 'El archivo no es una imagen válida. Usa JPG, PNG o WEBP.'


def validate_image_upload(file):
    """Validate an uploaded image and return its real format (``'JPEG'``, ``'PNG'``, ``'WEBP'``).

    Checks the declared content type, the size and, with Pillow, that the bytes
    really are an image, so a renamed text or script file is rejected.
    """
    if getattr(file, 'content_type', None) not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ValidationError(IMAGE_ERROR, code='invalid_image')
    if file.size > MAX_IMAGE_BYTES:
        raise ValidationError('La imagen supera el tamaño máximo de 5 MB.', code='image_too_large')
    try:
        file.seek(0)
        with Image.open(file) as image:
            image_format = image.format
            image.verify()
    except Exception:
        raise ValidationError(IMAGE_ERROR, code='invalid_image')
    finally:
        file.seek(0)
    if image_format not in IMAGE_EXTENSIONS:
        raise ValidationError(IMAGE_ERROR, code='invalid_image')
    return image_format


class ImageUploadField(forms.FileField):
    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)
        self.validators.append(validate_image_upload)


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(ImageUploadField):
    """Several images in one input; each one goes through ``validate_image_upload``."""

    widget = MultipleImageInput

    def clean(self, data, initial=None):
        single_clean = super().clean
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)]


class PublicacionForm(forms.ModelForm):
    imagen_portada = ImageUploadField()
    galeria = MultipleImageField()

    class Meta:
        model = Publicacion
        fields = ['titulo', 'resumen', 'contenido', 'categoria', 'estado']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = Categoria.objects.order_by('nombre')
        self.fields['categoria'].error_messages['invalid_choice'] = 'La categoría seleccionada no existe.'
        self.fields['estado'].required = False
        self.fields['estado'].error_messages['invalid_choice'] = 'El estado seleccionado no es válido.'
        self.fields['titulo'].error_messages['required'] = 'El título es obligatorio.'
        self.fields['resumen'].error_messages['required'] = 'El resumen es obligatorio.'
        self.fields['contenido'].error_messages['required'] = 'El contenido es obligatorio.'

    def clean_estado(self):
        return self.cleaned_data.get('estado') or Publicacion.ESTADO_BORRADOR


class ComentarioForm(forms.ModelForm):
    contenido = forms.CharField(
        max_length=2000,
        error_messages={'required': 'Escribe un comentario antes de enviarlo.'},
    )

    class Meta:
        model = Comentario
        fields = ['contenido']


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre']

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        duplicates = Categoria.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError('Ya existe una categoría con ese nombre.', code='duplicate')
        return nombre


class SignUpForm(BaseUserCreationForm):
    """Public sign-up. Password rules come from ``AUTH_PASSWORD_VALIDATORS``."""

    apellido_paterno = forms.CharField(max_length=80, required=False)
    apellido_materno = forms.CharField(max_length=80, required=False)

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('El correo electrónico ya está registrado.', code='duplicate')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        paterno = self.cleaned_data['apellido_paterno']
        materno = self.cleaned_data['apellido_materno']
        user.last_name = ' '.join(filter(None, [paterno, materno]))
        if commit:
            # All-or-nothing: no half-created account (user without role or unverified flag).
            with transaction.atomic():
                user.save()
                roles.assign_role(user, roles.COLABORADOR)
                perfil, _ = Perfil.objects.get_or_create(user=user)
                perfil.apellido_paterno = paterno
                perfil.apellido_materno = materno
                # Self-registered accounts must confirm their email before logging in.
                # This is the only place that sets email_verificado to False.
                perfil.email_verificado = False
                perfil.email_verificado_en = None
                perfil.save()
        return user


class PerfilForm(forms.Form):
    username = forms.CharField(max_length=150, error_messages={'required': 'El usuario es obligatorio.'})
    email = forms.EmailField(required=False)
    first_name = forms.CharField(max_length=150, required=False)
    apellido_paterno = forms.CharField(max_length=80, required=False)
    apellido_materno = forms.CharField(max_length=80, required=False)
    foto = ImageUploadField()

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exclude(pk=self.user.pk).exists():
            raise ValidationError('Ese nombre de usuario ya está en uso.', code='duplicate')
        return username


class ContactoForm(forms.ModelForm):
    # Honeypot: hidden from people, bots tend to fill every field.
    website = forms.CharField(required=False)
    mensaje = forms.CharField(max_length=5000, error_messages={'required': 'Escribe tu mensaje.'})

    class Meta:
        model = MensajeContacto
        fields = ['nombre', 'email', 'asunto', 'mensaje']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nombre'].error_messages['required'] = 'Escribe tu nombre.'
        self.fields['email'].error_messages['required'] = 'Escribe tu correo electrónico.'
        self.fields['email'].error_messages['invalid'] = 'Escribe un correo electrónico válido.'
        self.fields['asunto'].error_messages['required'] = 'Elige un asunto.'

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise ValidationError('No pudimos procesar tu mensaje.', code='spam')
        return ''


class _UsuarioPanelForm(forms.Form):
    """Shared fields and validation for the panel's create/edit user screens."""

    username = forms.CharField(max_length=150, error_messages={'required': 'El usuario es obligatorio.'})
    email = forms.EmailField(error_messages={
        'required': 'El correo electrónico es obligatorio.',
        'invalid': 'Escribe un correo electrónico válido.',
    })
    first_name = forms.CharField(max_length=150, required=False)
    apellido_paterno = forms.CharField(max_length=80, required=False)
    apellido_materno = forms.CharField(max_length=80, required=False)
    rol = forms.ChoiceField(
        required=False,
        choices=[(role.value, role.label) for role in roles.ROLES],
        error_messages={'invalid_choice': 'El rol seleccionado no es válido.'},
    )
    password1 = forms.CharField(required=False, strip=False)
    password2 = forms.CharField(required=False, strip=False)

    password_required = True

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        duplicates = User.objects.filter(username=username)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError('El usuario ya existe.', code='duplicate')
        return username

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1', '')
        password2 = cleaned.get('password2', '')
        if not password1 and not password2:
            if self.password_required:
                self.add_error('password1', 'La contraseña es obligatoria.')
            return cleaned
        if password1 != password2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
            return cleaned
        candidate = self.instance or User(
            username=cleaned.get('username', ''),
            email=cleaned.get('email', ''),
            first_name=cleaned.get('first_name', ''),
        )
        try:
            validate_password(password1, candidate)
        except ValidationError as error:
            self.add_error('password1', error)
        return cleaned

    def _apply(self, user):
        data = self.cleaned_data
        user.username = data['username']
        user.email = data['email']
        user.first_name = data['first_name']
        user.last_name = ' '.join(filter(None, [data['apellido_paterno'], data['apellido_materno']]))
        return user

    def _save_perfil(self, user):
        perfil, _ = Perfil.objects.get_or_create(user=user)
        perfil.apellido_paterno = self.cleaned_data['apellido_paterno']
        perfil.apellido_materno = self.cleaned_data['apellido_materno']
        perfil.save()


class UsuarioCreateForm(_UsuarioPanelForm):
    password_required = True

    def save(self):
        user = self._apply(User())
        user.set_password(self.cleaned_data['password1'])
        user.save()
        # A blank role falls back to the default (least privileged) one.
        roles.assign_role(user, self.cleaned_data['rol'] or roles.DEFAULT_ROLE)
        self._save_perfil(user)
        return user


class UsuarioEditForm(_UsuarioPanelForm):
    """Edit an existing user. Blank password keeps the current one; blank role keeps the current role."""

    password_required = False

    def __init__(self, *args, instance, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)
        self.fields['email'].required = False

    def save(self):
        user = self._apply(self.instance)
        if self.cleaned_data['password1']:
            user.set_password(self.cleaned_data['password1'])
        user.save()
        if self.cleaned_data['rol']:
            roles.assign_role(user, self.cleaned_data['rol'])
        self._save_perfil(user)
        return user


class VerifiedAuthenticationForm(AuthenticationForm):
    """Login form that also requires a confirmed email (blocked users keep Django's message)."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        perfil = getattr(user, 'perfil', None)
        if perfil is not None and not perfil.email_verificado:
            raise ValidationError(
                'Confirma tu correo electrónico antes de iniciar sesión. '
                'Si no recibiste el enlace, solicita uno nuevo en la página de reenvío de verificación.',
                code='email_not_verified',
            )


class ResendVerificationForm(forms.Form):
    email = forms.EmailField(max_length=254)
