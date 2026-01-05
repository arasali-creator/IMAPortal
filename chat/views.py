from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.models import Employee
from .models import ChatRoom, ChatMessage, ChatRoomMember


@login_required
def chat_home(request):
    qs = ChatRoom.objects.filter(members=request.user).distinct().prefetch_related("members")
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

    members_qs = Employee.objects.exclude(pk=request.user.pk).order_by("full_name", "email")

    context = {
        "rooms": rooms,
        "members": list(members_qs),
        "current_user_id": request.user.pk,
        "messages_url": reverse("chat_messages", args=[0]).replace("/0/", "/"),
        "create_room_url": reverse("chat_create_room"),
        "unread_count_url": reverse("chat_unread_count"),
    }
    return render(request, "chat/chat.html", context)


@login_required
def chat_messages(request, room_id: int):
    room = ChatRoom.objects.filter(pk=room_id, members=request.user).first()
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


@login_required
def chat_create_room(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=400)

    room_type = request.POST.get("room_type")
    member_ids = request.POST.getlist("members")
    room_name = request.POST.get("room_name", "").strip()

    if not member_ids:
        return JsonResponse({"ok": False, "error": "Select at least one member."}, status=400)

    member_ids = [int(x) for x in member_ids]
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


@login_required
def chat_unread_count(request):
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
