import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from accounts.models import Employee
from .models import ChatRoom, ChatMessage


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close()
            return

        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        room = await self._get_room(self.room_id)
        if not room:
            await self.close()
            return

        is_member = await self._is_member(room, user)
        if not is_member:
            await self.close()
            return

        self.room_group_name = f"chat_room_{self.room_id}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        payload = json.loads(text_data)
        msg_type = payload.get("type", "message")
        if msg_type == "typing":
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat.typing",
                    "sender_id": self.scope["user"].pk,
                    "is_typing": bool(payload.get("is_typing")),
                },
            )
            return
        if msg_type == "read":
            await self._mark_read(self.room_id, self.scope["user"])
            return

        message = payload.get("message", "").strip()
        if not message:
            return

        user = self.scope["user"]
        msg = await self._create_message(self.room_id, user, message)
        await self._mark_read(self.room_id, user)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.message",
                "message": msg["message"],
                "sender": msg["sender"],
                "timestamp": msg["timestamp"],
                "sender_id": msg["sender_id"],
                "avatar": msg["avatar"],
            },
        )

    async def chat_message(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "message": event["message"],
                    "sender": event["sender"],
                    "sender_id": event["sender_id"],
                    "timestamp": event["timestamp"],
                    "avatar": event.get("avatar", ""),
                }
            )
        )

    async def chat_typing(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "typing",
                    "sender_id": event.get("sender_id"),
                    "is_typing": event.get("is_typing", False),
                }
            )
        )

    @sync_to_async
    def _get_room(self, room_id):
        try:
            return ChatRoom.objects.get(pk=room_id)
        except ChatRoom.DoesNotExist:
            return None

    @sync_to_async
    def _is_member(self, room, user):
        return room.members.filter(pk=user.pk).exists()

    @sync_to_async
    def _create_message(self, room_id, user, message):
        room = ChatRoom.objects.get(pk=room_id)
        msg = ChatMessage.objects.create(room=room, sender=user, message=message)
        sender = getattr(user, "full_name", None) or getattr(user, "email", str(user))
        avatar_url = ""
        if getattr(user, "profile_picture", None):
            try:
                avatar_url = user.profile_picture.url
            except Exception:
                avatar_url = ""
        return {
            "message": msg.message,
            "sender": sender,
            "sender_id": user.pk,
            "timestamp": msg.created_at.strftime("%b %d, %I:%M %p"),
            "avatar": avatar_url,
        }

    @sync_to_async
    def _mark_read(self, room_id, user):
        from .models import ChatRoomMember

        ChatRoomMember.objects.update_or_create(
            room_id=room_id, user_id=user.pk, defaults={"last_read_at": ChatMessage.objects.filter(room_id=room_id).order_by("-created_at").values_list("created_at", flat=True).first()}
        )
