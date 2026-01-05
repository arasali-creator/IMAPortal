from django.urls import path
from . import views

urlpatterns = [
    path("", views.chat_home, name="chat_home"),
    path("messages/<int:room_id>/", views.chat_messages, name="chat_messages"),
    path("create-room/", views.chat_create_room, name="chat_create_room"),
    path("unread-count/", views.chat_unread_count, name="chat_unread_count"),
]
