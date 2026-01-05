from django.contrib import admin
from django.http import JsonResponse, Http404
from django.urls import path, reverse
from django.utils import timezone
from django.db.models import Q

from accounts.models import Employee, Team
from unfold.admin import ModelAdmin

from .models import ChatRoom, ChatMessage, ChatRoomMember


@admin.register(ChatRoom)
class ChatRoomAdmin(ModelAdmin):
    change_list_template = "admin/chat/chatroom/change_list.html"
    list_display = ("name", "is_group", "created_by", "created_at")
    search_fields = ("name", "members__full_name", "members__email")

    def get_queryset(self, request):
        qs = super().get_queryset(request).prefetch_related("members")
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return qs
        if getattr(request.user, "role", None) == "pm":
            return qs.filter(members=request.user)
        return qs.none()

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, "role", None) == "admin":
            return True
        return request.user.has_perm("chat.view_chatroom")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "messages/<int:room_id>/",
                self.admin_site.admin_view(self.messages_view),
                name="chat_room_messages",
            ),
            path(
                "create-room/",
                self.admin_site.admin_view(self.create_room_view),
                name="chat_room_create",
            ),
            path(
                "unread-count/",
                self.admin_site.admin_view(self.unread_count_view),
                name="chat_room_unread_count",
            ),
        ]
        return custom + urls

    def changelist_view(self, request, extra_context=None):
        qs = self.get_queryset(request)
        rooms = []
        for room in qs:
            members = list(room.members.all())
            if room.is_group:
                display = room.name or "Group chat"
                avatar = ""
            else:
                other = next((m for m in members if m.pk != request.user.pk), None)
                display = other.full_name if other and other.full_name else (other.email if other else "Direct chat")
                avatar = ""
                if other and getattr(other, "profile_picture", None):
                    try:
                        avatar = other.profile_picture.url
                    except Exception:
                        avatar = ""
            last_msg = room.messages.order_by("-created_at").first()
            membership = ChatRoomMember.objects.filter(room=room, user=request.user).first()
            last_read = membership.last_read_at if membership else None
            unread_qs = room.messages.exclude(sender=request.user)
            if last_read:
                unread_qs = unread_qs.filter(created_at__gt=last_read)
            unread_count = unread_qs.count()
            rooms.append(
                {
                    "id": room.pk,
                    "name": display,
                    "is_group": room.is_group,
                    "last_message": last_msg.message[:60] if last_msg else "No messages yet",
                    "last_time": last_msg.created_at.strftime("%b %d, %I:%M %p") if last_msg else "",
                    "avatar": avatar,
                    "unread_count": unread_count,
                    "is_unread": unread_count > 0,
                }
            )

        members_qs = Employee.objects.all().order_by("full_name", "email")

        extra_context = extra_context or {}
        extra_context.update(
            {
                "rooms": rooms,
                "members": list(members_qs),
                "current_user_id": request.user.pk,
                "messages_url": reverse("admin:chat_room_messages", args=[0]).replace("/0/", "/"),
                "create_room_url": reverse("admin:chat_room_create"),
                "unread_count_url": reverse("admin:chat_room_unread_count"),
            }
        )
        return super().changelist_view(request, extra_context=extra_context)

    def messages_view(self, request, room_id: int):
        room = self.get_queryset(request).filter(pk=room_id).first()
        if not room:
            raise Http404
        ChatRoomMember.objects.update_or_create(
            room_id=room_id, user_id=request.user.pk, defaults={"last_read_at": timezone.now()}
        )
        messages = (
            ChatMessage.objects.filter(room=room)
            .select_related("sender")
            .order_by("created_at")[:200]
        )
        data = []
        for msg in messages:
            sender = msg.sender.full_name or msg.sender.email or str(msg.sender)
            avatar_url = ""
            if getattr(msg.sender, "profile_picture", None):
                try:
                    avatar_url = msg.sender.profile_picture.url
                except Exception:
                    avatar_url = ""
            data.append(
                {
                    "id": msg.pk,
                    "sender": sender,
                    "sender_id": msg.sender_id,
                    "message": msg.message,
                    "timestamp": msg.created_at.strftime("%b %d, %I:%M %p"),
                    "avatar": avatar_url,
                }
            )
        return JsonResponse({"ok": True, "messages": data})

    def create_room_view(self, request):
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": "POST only"}, status=400)

        room_type = request.POST.get("room_type")
        member_ids = request.POST.getlist("members")
        room_name = request.POST.get("room_name", "").strip()

        if not member_ids:
            return JsonResponse({"ok": False, "error": "Select at least one member."}, status=400)

        member_ids = [int(x) for x in member_ids]
        # PM can start chats with any employee, but can only see rooms they belong to.
        if request.user.pk not in member_ids:
            member_ids.append(request.user.pk)

        if room_type == "direct":
            if len(member_ids) != 2:
                return JsonResponse({"ok": False, "error": "Direct chat must have exactly one member."}, status=400)
            direct_key = ChatRoom.build_direct_key(member_ids[0], member_ids[1])
            room, _created = ChatRoom.objects.get_or_create(
                direct_key=direct_key,
                defaults={"is_group": False, "created_by": request.user},
            )
        else:
            room = ChatRoom.objects.create(
                name=room_name or "Group chat",
                is_group=True,
                created_by=request.user,
            )

        room.members.set(Employee.objects.filter(id__in=member_ids))
        room.save(update_fields=["name", "is_group", "direct_key", "created_by"])
        ChatRoomMember.objects.update_or_create(
            room_id=room.pk, user_id=request.user.pk, defaults={"last_read_at": timezone.now()}
        )

        return JsonResponse({"ok": True, "room_id": room.pk})

    def unread_count_view(self, request):
        total = 0
        rooms = ChatRoom.objects.filter(members=request.user).distinct()
        for room in rooms:
            membership = ChatRoomMember.objects.filter(room=room, user=request.user).first()
            last_read = membership.last_read_at if membership else None
            qs = room.messages.exclude(sender=request.user)
            if last_read:
                qs = qs.filter(created_at__gt=last_read)
            total += qs.count()
        return JsonResponse({"ok": True, "count": total})


@admin.register(ChatMessage)
class ChatMessageAdmin(ModelAdmin):
    list_display = ("room", "sender", "short_message", "created_at")
    list_filter = ("room", "sender")
    search_fields = ("message", "sender__full_name", "sender__email")
    readonly_fields = ("room", "sender", "message", "created_at")

    def short_message(self, obj):
        return (obj.message[:60] + "…") if obj.message and len(obj.message) > 60 else obj.message
    short_message.short_description = "Message"
