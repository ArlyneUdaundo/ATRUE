from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.contrib.auth import authenticate
import re
from datetime import date

from .models import ACCOUNT_TYPE_CHOICES, NATIONALITY_CHOICES, SEX_CHOICES, User

SUFFIX_CHOICES = [('', '— Select suffix —')] + [
    (s, s) for s in ('Jr.', 'Sr.', 'III', 'IV', 'V', 'VI', 'VII')
]

CONTACT_RE = re.compile(r'^\d{11}$')

# FR-001 Create User Account INPUT order (ATRUE_FR.md module 1).
FR_FIELD_ORDER = (
    'last_name', 'first_name', 'middle_initial', 'middle_name', 'suffix',
    'date_of_birth', 'sex', 'email', 'contact_number', 'residential_address',
    'nationality', 'emergency_contact_name', 'emergency_contact_number',
    'emergency_contact_relationship', 'account_type', 'status',
    'password1', 'password2', 'username',
)


def _reorder_fields(form):
    """Reorder the form fields to follow the FR INPUT arrangement."""
    ordered = {name: form.fields[name] for name in FR_FIELD_ORDER if name in form.fields}
    ordered.update({name: form.fields[name] for name in form.fields if name not in ordered})
    form.fields = ordered


def _validate_phone(value, label="Number"):
    num = (value or '').strip()
    if num and not CONTACT_RE.match(num):
        raise forms.ValidationError(f"{label} must contain exactly 11 digits.")
    return num


class UserLoginForm(AuthenticationForm):
    """Sign-in by email address or username (BR-001, FR-001)."""

    username = forms.CharField(label="Email or username", max_length=254)

    def clean(self):
        value = self.cleaned_data.get('username', '')
        if not value:
            raise forms.ValidationError("Enter your email or username.")
        user = User.objects.filter(email=value.strip().lower()).first()
        if user is not None:
            self.cleaned_data['username'] = user.username
        return super().clean()


class UserRegistrationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'date_of_birth' in self.fields:
            self.fields['date_of_birth'].widget.attrs.update({
                'type': 'date', 'max': date.today().isoformat(),
            })

    def clean_date_of_birth(self):
        value = self.cleaned_data.get('date_of_birth')
        if value and value > date.today():
            raise forms.ValidationError('Birthdate cannot be in the future.')
        return value

    # Username is derived from the email prefix (BR-001), so the field is
    # hidden from the UI and optional; clean_username fills it in.
    username = forms.CharField(required=False, max_length=150)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            'username', 'email', 'first_name', 'last_name',
            'middle_name', 'middle_initial', 'suffix',
            'date_of_birth', 'sex', 'nationality',
            'contact_number', 'residential_address',
            'emergency_contact_name', 'emergency_contact_number',
            'emergency_contact_relationship',
        )

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError("Email is required.")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_contact_number(self):
        return _validate_phone(self.cleaned_data.get('contact_number', ''), "Contact number")

    def clean_emergency_contact_number(self):
        return _validate_phone(self.cleaned_data.get('emergency_contact_number', ''), "Emergency contact number")

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not username:
            return username
        if not re.match(r'^[\w.@+-]+$', username):
            raise forms.ValidationError("Username may only contain letters, numbers, and @/./+/-/_ characters.")
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean(self):
        cleaned = super().clean()
        username = cleaned.get('username')
        if not username:
            cleaned['username'] = self._generate_username(cleaned.get('email') or 'user')
        return cleaned

    def _generate_username(self, email):
        base = email.split('@')[0]
        base = re.sub(r'[^a-zA-Z0-9_]', '', base)
        if not base:
            base = 'user'
        candidate = base
        counter = 1
        while User.objects.filter(username=candidate).exists():
            candidate = f"{base}{counter}"
            counter += 1
        return candidate

    def save(self, commit=True):
        user = super().save(commit=False)
        user.account_type = User.AccountType.STUDENT
        user.status = User.Status.ACTIVE
        if commit:
            user.save()
        return user


class AccountCreateForm(UserRegistrationForm):
    """FR-001 Create User Account.

    The System Administrator may create accounts of any type; Administrator and
    Instructor/Trainer accounts may create Student accounts only (USER_ROLE.md
    module 1 and platform rule).
    """

    MANAGER_CHOICES = [
        (User.AccountType.STUDENT, 'Student'),
        (User.AccountType.GUEST_HOTEL, 'Guest – Hotel'),
        (User.AccountType.INSTRUCTOR, 'Instructor/Trainer'),
        (User.AccountType.ADMIN, 'Administrator'),
    ]

    account_type = forms.ChoiceField(
        choices=MANAGER_CHOICES,
        initial=User.AccountType.STUDENT,
        label="Account Type",
        widget=forms.Select(),
    )

    class Meta(UserRegistrationForm.Meta):
        fields = UserRegistrationForm.Meta.fields + ('account_type',)

    def __init__(self, *args, creator=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('profile_picture', None)
        from accounts.roles import can_create_any_account
        if creator is not None and can_create_any_account(creator):
            self.fields['account_type'].choices = ACCOUNT_TYPE_CHOICES
        self.fields['suffix'].widget = forms.Select(
            choices=SUFFIX_CHOICES, attrs={'class': 'form-input'})
        self.fields['sex'].widget = forms.Select(
            choices=[('', ' ')] + SEX_CHOICES, attrs={'class': 'form-input'})
        self.fields['nationality'].widget = forms.Select(
            choices=[('', '-- Select nationality --')] + NATIONALITY_CHOICES, attrs={'class': 'form-input'})
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
        self.fields['username'].required = True
        self.fields['username'].help_text = 'The exact username the user will sign in with.'
        self.fields['date_of_birth'].widget.input_type = 'date'
        self.fields['date_of_birth'].widget.attrs['max'] = date.today().isoformat()
        self.fields['contact_number'].widget.attrs.update({'inputmode': 'numeric', 'pattern': '[0-9]{11}', 'maxlength': 11, 'placeholder': '09XXXXXXXXX', 'oninput': "this.value=this.value.replace(/\D/g,'')"})
        self.fields['emergency_contact_number'].widget.attrs.update({'inputmode': 'numeric', 'pattern': '[0-9]{11}', 'maxlength': 11, 'oninput': "this.value=this.value.replace(/\D/g,'')"})
        _reorder_fields(self)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.account_type = self.cleaned_data.get('account_type', User.AccountType.STUDENT)
        user.status = User.Status.ACTIVE
        if commit:
            user.save()
        return user


class ProfilePhotoForm(forms.Form):
    """Upload, replace or remove the signed-in user's profile photo.

    Kept separate from :class:`UserAccountForm` because the profile header is the
    only place a photo should change from: a photo is one thing, while that form
    also edits identity and contact fields that an administrator controls. Only
    the owner ever gets this form, so it carries no permission logic of its own.

    Django's own ``ClearableFileInput`` supplies the "remove" affordance; the
    checkbox posts ``profile_photo-clear`` and clears the field on save.
    """

    #: A profile photo is decoration, not a document. Anything larger is almost
    #: certainly a phone camera original rather than something chosen for a
    #: 160px avatar, and it would be served on every authenticated page.
    MAX_BYTES = 2 * 1024 * 1024

    profile_picture = forms.ImageField(
        required=False,
        # ``id`` is in ``attrs``, not a widget keyword: the header's camera button
        # opens this input by id, and Django's default ``id_profile_picture`` would
        # tie the template to the field name. The same attr is set per instance in
        # ``__init__`` so an unbound form still renders it.
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        help_text='JPEG or PNG, up to 2 MB. A square image looks best.',
    )

    #: Overrides the rendered ``id`` of the file input, which the profile header's
    #: camera button and the photo panel's JavaScript both look up.
    input_id = 'profilePhotoInput'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profile_picture'].widget.attrs['id'] = self.input_id

    def clean_profile_picture(self):
        """Reject an oversized upload.

        Whether the file is really an image is already settled: ``ImageField``
        runs Pillow over it while cleaning, so a text file renamed to ``.png``
        never reaches this method.
        """
        photo = self.cleaned_data.get('profile_picture')
        if photo and photo.size > self.MAX_BYTES:
            raise forms.ValidationError(
                'That image is %.1f MB. Please choose one under 2 MB.'
                % (photo.size / (1024 * 1024)))
        return photo

    def save(self, user):
        """Apply the upload or the clear to ``user`` and persist it."""
        photo = self.cleaned_data.get('profile_picture')
        # ``data.get('profile_picture-clear')`` rather than the field's own
        # ``value``: that is the flag Django sets when the remove box is ticked,
        # and it must win over a simultaneously chosen file.
        if self.data.get(self.add_prefix('profile_picture-clear')):
            user.profile_picture.delete(save=False)
            user.profile_picture = None
        elif photo:
            # Assigning replaces the field, and the old file is left on disk
            # unless it is deleted, so a replaced photo does not accumulate.
            if user.profile_picture:
                user.profile_picture.delete(save=False)
            user.profile_picture = photo
        user.save(update_fields=['profile_picture'])
        return user


class UserAccountForm(forms.ModelForm):
    """FR-004 UPDATE User Account. System Administrator / Administrator editors
    may also adjust the account status and type; everyone else (including the
    Instructor/Trainer) edits only their own profile without those fields."""

    class Meta:
        model = User
        fields = (
            'first_name', 'last_name', 'middle_name', 'middle_initial', 'suffix', 'email',
            'date_of_birth', 'sex', 'nationality',
            'contact_number', 'residential_address',
            'emergency_contact_name', 'emergency_contact_number',
            'emergency_contact_relationship', 'profile_picture',
            'status', 'account_type',
        )
        widgets = {
            'sex': forms.Select(choices=SEX_CHOICES),
            'nationality': forms.Select(choices=NATIONALITY_CHOICES),
            'suffix': forms.Select(choices=SUFFIX_CHOICES),
            'date_of_birth': forms.DateInput(attrs={'type': 'date', 'max': date.today().isoformat()}),
            'status': forms.Select(),
            'account_type': forms.Select(),
        }

    def __init__(self, *args, as_admin=False, allow_profile_picture=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not allow_profile_picture:
            self.fields.pop('profile_picture')
        if not as_admin:
            self.fields.pop('status')
            self.fields.pop('account_type')
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-input'
        if 'profile_picture' in self.fields:
            self.fields['profile_picture'].widget.attrs['accept'] = 'image/*'
            self.fields['profile_picture'].help_text = (
                'Upload an image for the blue avatar beside your name. '
                'Select Clear to remove the current picture.'
            )
        self.fields['contact_number'].widget.attrs.update({'inputmode': 'numeric', 'pattern': '[0-9]{11}', 'maxlength': 11, 'oninput': "this.value=this.value.replace(/\D/g,'')"})
        self.fields['emergency_contact_number'].widget.attrs.update({'inputmode': 'numeric', 'pattern': '[0-9]{11}', 'maxlength': 11, 'oninput': "this.value=this.value.replace(/\D/g,'')"})
        self.fields['email'].widget.attrs.update({'type': 'email', 'autocomplete': 'email', 'maxlength': 254})
        _reorder_fields(self)

    def clean_date_of_birth(self):
        value = self.cleaned_data.get('date_of_birth')
        if value and value > date.today():
            raise forms.ValidationError('Birthdate cannot be in the future.')
        return value

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().casefold()
        if not email:
            raise forms.ValidationError('Email address is required.')
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean_contact_number(self):
        return _validate_phone(self.cleaned_data.get('contact_number', ''), "Contact number")

    def clean_emergency_contact_number(self):
        return _validate_phone(self.cleaned_data.get('emergency_contact_number', ''), "Emergency contact number")
