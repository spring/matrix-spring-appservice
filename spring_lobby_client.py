# -*- coding: utf-8 -*-

#   Copyright (c) 2020 TurBoss
#         <turboss@mail.com>
#
#   This file is part of Matrix Spring Appservice.
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import logging
import sys
from pprint import pprint

from asyncblink import signal as asignal

from collections import defaultdict

from asyncspring.lobby import LobbyProtocol, LobbyProtocolWrapper, connections
from mautrix.appservice import AppService
from mautrix.client.api.types import PresenceState, Membership, Member, RoomID, UserID


class SpringLobbyClient(object):
    log: logging.Logger
    appserv: AppService

    def __init__(self, appserv, config, loop):

        self.log = logging.getLogger("lobby")  # type: logging.Logger

        self.bot = None
        self.rooms = None
        self.user_rooms = defaultdict(list)
        self.appserv = appserv
        self.presence_timmer = None
        self.bot_username = None
        self.bot_password = None

        self.config = config

        self.loop = loop

    async def start(self):

        self.log.info("Starting Spring lobby client")

        await self.appserv.intent.set_presence(PresenceState.ONLINE)

        self.bot = await self.connect(server=self.config["spring.address"],
                                      port=self.config["spring.port"],
                                      use_ssl=self.config["spring.ssl"],
                                      name=self.config["spring.client_name"],
                                      flags=self.config["spring.client_flags"])

        self.rooms = self.config["bridge.rooms"]

        self.log.debug("### CONFIG ROOMS ###")

        for room_name, room_data in self.rooms.items():
            channel = f"#{room_name}"
            room_id = room_data["room_id"],
            room_enabled = room_data["enabled"]

            self.log.info(f"{room_enabled} channel : {channel} room_name : {room_name} room_id : {room_id}")
            if room_enabled:
                self.bot.channels_to_join.append(channel)
                await self.appserv.intent.join_room(room_id[0])

        bot_username = self.config["spring.bot_username"]
        bot_password = self.config["spring.bot_password"]

        self.bot.login(bot_username, bot_password)

    async def _presence_timer(self, user):
        self.log.debug(f"SET presence timmer for user : {user}")
        user.set_presence(PresenceState.ONLINE)

    async def leave_matrix_rooms(self, username):
        user = self.appserv.intent.user(username)
        for room in await user.get_joined_rooms():
            await user.leave_room(room)

    async def login_matrix_account(self, user_name):

        self.log.debug(f"User {user_name} joined from lobby")
        domain = self.config['homeserver.domain']

        # namespace = self.config['appservice.namespace']
        # matrix_id = f"@{namespace}_{user_name.lower()}:{domain}"
        # user = self.appserv.intent.user(matrix_id)
        #
        # user.set_presence(PresenceState.ONLINE)
        # user.set_display_name(user_name)
        #
        # self.presence_timmer = asyncio.get_event_loop().call_later(29, self._presence_timer, user)

        self.bot.bridged_client_from(domain, user_name.lower, user_name)

    async def logout_matrix_account(self, user_name):
        self.log.debug(f"User {user_name} leave lobby")

        domain = self.config['homeserver.domain']
        namespace = self.config['appservice.namespace']
        matrix_id = f"@{namespace}_{user_name.lower()}:{domain}"
        user = self.appserv.intent.user(UserID(matrix_id))

        rooms = await user.get_joined_rooms()

        for room_id in rooms:
            await user.leave_room(room_id=room_id)

        # await user.set_presence("offline")
        # self.presence_timmer.cancel()
        self.bot.un_bridged_client_from(domain, user_name)

    # async def clean_matrix_rooms(self):
    #
    #     for room_name, room_data in self.rooms.items():
    #         channel = room_name
    #         room_id = room_data["room_id"]
    #         enabled = room_data["enabled"]
    #
    #         self.log.debug(f"removing logged users from {channel}")
    #
    #         members = await self.appserv.intent.get_room_members(room_id=room_id)
    #
    #         for member in members:
    #             namespace = self.config['appservice.namespace']
    #             if member.startswith(f"@{namespace}_"):
    #                 self.log.debug(f"user {member}")
    #                 user = self.appserv.intent.user(user=member)
    #                 await user.leave_room(room_id)

    async def sync_matrix_users(self) -> None:
        self.log.debug("Sync matrix users")

        bot_username = self.config["appservice.bot_username"]

        for room_name, room_data in self.rooms.items():
            spring_room = room_data.get('name')
            room_id = RoomID(room_data.get("room_id"))
            enabled = room_data.get("enabled")

            if enabled is True:
                self.log.debug(f"Room {spring_room} enabled")
                await self.appserv.intent.ensure_joined(room_id=room_id)
                resp = await self.appserv.intent.get_room_joined_memberships(room_id)
                members = resp["joined"]
                for mxid, info in members.items():
                    member = Member(membership=Membership.JOIN)
                    if "display_name" in info:
                        member.displayname = info["display_name"]
                    if "avatar_url" in info:
                        member.avatar_url = info["avatar_url"]

                    if mxid.startswith(f"@{bot_username}") is not True:
                        self.log.debug(f"StateStore: set member room_id {room_id} mxid {mxid} member {member}")
                        self.appserv.state_store.set_member(room_id, mxid, member)
            else:
                self.log.debug(f"Room {spring_room} disabled")

        # Unique matrix users in all bridged rooms
        matrix_users = set(val for key, dic in self.appserv.state_store.members.items() for val in dic.keys())

        for user in matrix_users:
            location = self.appserv.intent.user(user_id=UserID(user)).domain
            external_id = self.appserv.intent.user(user_id=UserID(user)).localpart
            external_username = await self.appserv.intent.get_displayname(UserID(user)) or external_id

            if external_id != self.config["appservice.bot_username"]:
                if external_id.startswith(self.config["appservice.namespace"]) is False:

                    self.log.debug(f"Bridging user {user} for {location} externalID {external_id} externalUsername {external_username}")

                    if external_id.startswith("_discord_"):
                        external_id = external_id.lstrip("_discord_")
                        location = "discord"
                    elif external_id.startswith("freenode"):
                        external_id = external_id.lstrip("freenode_")
                        location = "freenode.org"

                    self.bot.bridged_client_from(location=location,
                                                 external_id=external_id,
                                                 external_username=external_username)
            else:
                self.log.debug(f"Ignoring local user {external_id}, domain {location}. external_username {external_username}")

        for room_id, members in self.appserv.state_store.members.items():

            await self.appserv.intent.ensure_joined(room_id=room_id)

            self.log.debug(f"RoomID: {room_id}")

            for member in members:
                self.log.debug(f"\tMember: {member}")

                user_name = self.appserv.intent.user(user_id=member).localpart
                domain = self.appserv.intent.user(user_id=member).domain
                display_name = await self.appserv.intent.get_room_displayname(room_id=room_id, user_id=member)
                #
                # if user_name == self.config['spring.bot_username'] or user_name == '_discord_bot':
                #     continue

                self.log.debug(f"user_name = {user_name}")
                self.log.debug(f"display_name = {display_name}")
                self.log.debug(f"domain = {domain}")

                if user_name.startswith("_discord"):
                    domain = "discord"
                    user_name = user_name.lstrip("_discord_")

                elif user_name.startswith("freenode"):
                    domain = "freenode.org"
                    user_name = user_name.lstrip("freenode_")

                if display_name:
                    display_name = display_name.lstrip('@')
                    display_name = display_name.replace('-', '_')
                    display_name = display_name.replace('.', '_')
                    if len(display_name) > 15:
                        display_name = display_name[:15]
                else:
                    display_name = user_name

                self.log.debug(f"user_name = {user_name}")
                self.log.debug(f"display_name = {display_name}")
                self.log.debug(f"domain = {domain}")

                for _, room in self.rooms.items():
                    if room.get("room_id") == room_id:
                        self.log.debug(f"Join channel {room.get('name')}, user {user_name}, domain {domain}")
                        self.bot.join_from(room.get("name"), domain, user_name)

    async def join_matrix_room(self, room, clients):

        room_id = self.rooms[room]["room_id"]
        self.log.debug(room_id)

        for client in clients:
            if client != "appservice":
                domain = self.config['homeserver.domain']
                namespace = self.config['appservice.namespace']
                matrix_id = f"@{namespace}_{client.lower()}:{domain}"
                user = self.appserv.intent.user(UserID(matrix_id))

                await user.join_room_by_id(room_id=room_id)

    async def leave_matrix_room(self, room, clients):
        self.log.debug("leaving matrix room left from lobby")
        self.log.debug(room)
        for client in clients:
            self.log.debug(client)
            if client != "spring":
                self.log.debug(f"CLIENT {client}")

                domain = self.config['homeserver.domain']
                namespace = self.config['appservice.namespace']

                matrix_id = f"@{namespace}_{client.lower()}:{domain}"
                self.log.debug(matrix_id)

                room_id = self.rooms[room]["room_id"]
                self.log.debug(room_id)

                user = self.appserv.intent.user(UserID(matrix_id))

                self.log.debug(user)
                await user.leave_room(room_id=room_id)

        self.log.debug("succes leaved matrix room left from lobby")

    #
    # async def create_matrix_room(self, room):
    #
    #     domain = self.config['homeserver.domain']
    #     namespace = self.config['appservice.namespace']
    #
    #     room_alias = f"#{namespace}_{room}:{domain}"
    #     try:
    #         room_id = await self.appserv.intent.create_room(alias=room_alias, is_public=True)
    #         await self.appserv.intent.join_room(room_id)
    #         self.log.debug(f"room created = {room_id}")
    #     except Exception as e:
    #         self.log.debug(e)
    #
    async def said(self, user, room, message):

        domain = self.config['homeserver.domain']
        namespace = self.config['appservice.namespace']

        matrix_id = f"@{namespace}_{user.lower()}:{domain}"

        room_id = self.rooms[room]["room_id"]

        user = self.appserv.intent.user(UserID(matrix_id))

        await user.send_text(room_id, message)

    async def saidex(self, user, room, message):

        domain = self.config['homeserver.domain']
        namespace = self.config['appservice.namespace']

        matrix_id = f"@{namespace}_{user.lower()}:{domain}"

        room_id = self.rooms[room]["room_id"]

        user = self.appserv.intent.user(UserID(matrix_id))

        await user.send_emote(room_id, message)

    async def matrix_user_joined(self, user_id, room_id, event_id=None):
        """
        Matrix user Joins the room
        """

        hs_domain = self.config['homeserver.domain']
        namespace = self.config['appservice.namespace']
        bot_username = self.config["appservice.bot_username"]

        if user_id == f"@{bot_username}:{hs_domain}":
            self.log.debug(f"Appservice joined {room_id}")
            return
        elif user_id.startswith(f"@{namespace}_") and user_id.endswith(f":{hs_domain}"):
            self.log.debug(f"Local user {user_id} joined room_id {room_id} ignoring")
            return

        # obtain the spring room name from config
        channel = None
        for room in self.rooms:
            if self.rooms[room]["room_id"] == room_id:
                channel = room

        user_domain = self.appserv.intent.user(user_id=user_id).domain
        user_name = self.appserv.intent.user(user_id=user_id).localpart

        # check is is the our appservice bot
        if user_name == self.config["appservice.bot_username"] and user_domain == self.config["homeserver.domain"]:
            return

        self.log.debug(f"Matrix user {user_name} joined room {room_id}")
        if event_id:
            await self.appserv.intent.mark_read(room_id=room_id, event_id=event_id)

        if user_name and user_domain:
            display_name = await self.appserv.intent.get_displayname(user_id=user_id)

            self.bot.bridged_client_from(user_domain, user_name, display_name)  # TODO check if already bridged
            self.log.debug(f"Matrix user {user_name} bridged")

            self.bot.join_from(channel, user_domain, user_name)
            self.log.debug(f"Matrix user {user_name} joined {channel}")

    async def matrix_user_left(self, user_id, room_id, event_id):

        spring_room = None
        for key in self.rooms:
            if self.rooms[key].get("room_id") == room_id:
                spring_room = key

        display_name = await self.appserv.intent.get_displayname(user_id=user_id)
        user_domain = self.appserv.intent.user(user_id=user_id).domain
        user_name = self.appserv.intent.user(user_id=user_id).localpart

        if event_id:
            await self.appserv.intent.mark_read(room_id=room_id, event_id=event_id)

        self.bot.leave_from(spring_room, user_domain, display_name)
        self.log.debug(f"Matrix user {user_name} leaves {spring_room}")

    async def say_from_matrix(self, user_id, room_id, event_id, body, emote=False):

        namespace = self.config['appservice.namespace']
        if user_id.startswith(f"@{namespace}"):
            return

        room_name = list(v.get('name') for _, v in self.rooms.items() if v.get('room_id') == room_id)[0]

        room_data = self.rooms.get(room_name)

        channel = room_data.get('name')
        stored_room_id = room_data.get('room_id')
        enabled = room_data.get('enabled')

        if enabled is False:
            self.log.debug(f"room id: {stored_room_id} active: {enabled}")
            return

        user_name = self.appserv.intent.user(user_id=UserID(user_id)).localpart
        domain = self.appserv.intent.user(user_id=UserID(user_id)).domain

        if user_name.startswith("_discord"):
            domain = "discord"
            user_name = user_name.lstrip("_discord_")

        elif user_name.startswith("freenode_"):
            domain = "frenode.org"
            user_name = user_name.lstrip("freenode_")

        # if emote is True:
        #     self.bot.say_ex(user_name, domain, channel, body)
        # else:
        self.bot.say_from(user_name, domain, channel, body)

        await self.appserv.intent.mark_read(room_id=room_id, event_id=event_id)

    async def exit(self, signal_name):
        self.log.debug("Singal received exiting")
        # await self.clean_matrix_rooms()
        # loop.stop()
        sys.exit(0)

    def login(self, args=None):
        for channel in self.rooms:
            self.bot.channels_to_join.append(channel)
        self.bot.login(self.config["spring.bot_username"], self.config["spring.bot_password"])

    async def connect(self, server, port=8200, use_ssl=False, name=None, flags=None):
        """
        Connect to an SpringRTS Lobby server. Returns a proxy to an LobbyProtocol object.
        """
        protocol = None
        while protocol is None:
            try:
                transport, protocol = await self.loop.create_connection(LobbyProtocol,
                                                                        host=server,
                                                                        port=port,
                                                                        ssl=use_ssl)
            except ConnectionRefusedError as conn_error:
                self.log.info(f"HOST DOWN! retry in 10 secs {conn_error}")
                await asyncio.sleep(10)

        self.log.info("connected")
        protocol.wrapper = LobbyProtocolWrapper(protocol)
        protocol.server_info = {"host": server, "port": port, "ssl": use_ssl}
        protocol.netid = f"{id(protocol)}:{server}:{port}{'+' if use_ssl else '-'}"

        if name is not None:
            protocol.name = name

        if flags is not None:
            protocol.flags = flags

        asignal("netid-available").send(protocol)

        connections[protocol.netid] = protocol.wrapper

        return protocol.wrapper

    async def reconnect(self, client_wrapper):
        protocol = None
        server_info = client_wrapper.server_info

        self.log.info("reconnecting")
        while protocol is None:
            await asyncio.sleep(10)
            try:
                transport, protocol = await self.loop.create_connection(LobbyProtocol, **server_info)
                client_wrapper.protocol = protocol

                asignal("netid-available").send(protocol)

                asignal("reconnected").send()

            except ConnectionRefusedError as conn_error:
                self.log.info(f"HOST DOWN! retry in 10 secs {conn_error}")
