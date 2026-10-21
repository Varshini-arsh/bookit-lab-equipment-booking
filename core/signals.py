from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=User)
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        role = Profile.Role.MANAGER if instance.is_superuser else Profile.Role.MEMBER
        Profile.objects.get_or_create(user=instance, defaults={"role": role})
