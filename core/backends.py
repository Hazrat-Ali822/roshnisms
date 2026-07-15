from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q

class EmailOrUsernameBackend(ModelBackend):
    """
    Custom authentication backend that allows logging in using either
    the username or the email address (case-insensitive).
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or not username.strip():
            return None
        
        # Match against username OR email using filter to handle potential duplicates (e.g. empty emails)
        users = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username))
        for user in users:
            if user.check_password(password):
                return user
        return None
