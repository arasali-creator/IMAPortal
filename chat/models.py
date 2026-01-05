from django.db import models
from django.utils import timezone

from accounts.models import Employee


class ChatRoom(models.Model):
    name = models.CharField(max_length=120, blank=True)
    is_group = models.BooleanField(default=False)
    direct_key = models.CharField(max_length=64, unique=True, blank=True)
    created_by = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_rooms"
    )
    members = models.ManyToManyField(
        Employee, through="ChatRoomMember", related_name="chat_rooms", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.is_group:
            return self.name or "Group chat"
        return self.name or "Direct chat"

    @staticmethod
    def build_direct_key(user_a_id: int, user_b_id: int) -> str:
        a, b = sorted([int(user_a_id), int(user_b_id)])
        return f"direct-{a}-{b}"


class ChatMessage(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="sent_messages")
    message = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender} -> {self.room}: {self.message[:30]}"


class ChatRoomMember(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="chat_memberships")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("room", "user")
