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

import re

from asyncblink import signal as asignal

from asyncspring.lobby import LobbyProtocol, LobbyProtocolWrapper, connections
from mautrix.appservice import AppService
from mautrix.errors import MNotFound, MUnknown
from mautrix.types import PresenceState, UserID, RoomID, Member, Membership


class SpringLobbyClient(object):
    log: logging.Logger
    appserv: AppService

    def __init__(self, appserv, config, loop):

        self.log: logging.Logger = logging.getLogger("lobby")

        self.config = config

        self.bot = None
        self.appserv = appserv
        self.presence_timmer = None
        self.bot_username = self.config["spring.bot_username"]
        self.bot_password = self.config["spring.bot_password"]
        self.client_flags = self.config["spring.client_flags"]
        self.server = self.config["spring.address"]
        self.port = self.config["spring.port"]
        self.use_ssl = self.config["spring.ssl"]
        self.client_name = self.config["spring.client_name"]
        self.rooms = self.config["bridge.rooms"]
        self.enabled_rooms = list()

        self.loop = loop

    async def start(self):

        self.log.info("Starting Spring lobby client")

        server = self.server
        port = self.port
        use_ssl = self.use_ssl
        client_name = self.client_name

        await self.appserv.intent.set_presence(PresenceState.ONLINE)

        self.bot = await self.connect(server=server,
                                      port=port,
                                      use_ssl=use_ssl,
                                      name=client_name)

        self.log.debug("### Channels to join ###")
        for room_name, room_data in self.rooms.items():
            if room_data['enabled'] is True:
                self.log.debug(f"Join {room_name}")
                self.bot.channels_to_join.append(room_name)
            else:
                self.log.debug(f"Not join {room_name}")

    async def config_rooms(self):

        self.log.debug("### CONFIG ROOMS ###")

        for room_name, room_data in self.rooms.items():
            channel = f"#{room_name}"
            room_id = room_data["room_id"],
            room_enabled = room_data["enabled"]

            self.log.info(f"{room_enabled} channel : {channel} room_name : {room_name} room_id : {room_id}")
            if room_enabled is True:
                self.bot.channels_to_join.append(channel)
                await self.appserv.intent.join_room(room_id[0])
                self.enabled_rooms.append(room_id[0])
            else:
                try:
                    await self.appserv.intent.leave_room(room_id[0])
                    self.log.debug("Appservice leaves this room")
                except MUnknown as mu:
                    self.log.debug("Appservice not in this room")

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

            if enabled:
                self.log.debug(f"Room {spring_room} enabled")
                await self.appserv.intent.ensure_joined(room_id=room_id)
                members = await self.appserv.intent.get_room_members(room_id)

                for mxid in members:

                    self.log.debug(f"member {mxid}")

                    member = await self.appserv.intent.get_room_member_info(room_id=room_id, user_id=mxid)

                    if mxid.startswith(f"@{bot_username}"):
                        self.log.debug(f"Ignore myself {mxid}")

                    elif mxid.startswith(f"@{self.config['appservice.namespace']}_"):
                        self.log.debug(f"Ignoring local user {mxid}")
                    else:
                        self.log.debug(f"Loging user {mxid}")
                        await self.appserv.state_store.set_member(room_id, mxid, member)
            else:
                self.log.debug(f"Room {spring_room} disabled")

        self.log.debug("Start bridging users")

        bridged_clients = list()
        for room_name, room_data in self.rooms.items():
            enabled = room_data.get("enabled")
            if enabled:
                room_id = RoomID(room_data.get("room_id"))
                room_users = await self.appserv.intent.get_room_members(room_id)
                for user in room_users:
                    bridged_clients.append(user)

        for member in list(set(bridged_clients)):
            self.log.debug(f"User {member}")
            localpart, domain = self.appserv.intent.parse_user_id(member)

            if localpart == "_discord_bot":
                continue

            try:
                displayname = await self.appserv.intent.get_displayname(UserID(member))
            except Exception as nf:
                self.log.error(f"user {localpart} has no profile {nf}")
                displayname = localpart

            if localpart.startswith("_discord_"):
                localpart = localpart.lstrip("_discord_")
                domain = "discord"
            elif localpart.startswith("freenode_"):
                localpart = localpart.lstrip("freenode_")
                domain = "freenode.org"
            elif localpart.startswith("spring_"):
                localpart = localpart.lstrip("spring_")
                domain = "springlobby"

            if len(displayname) > 15:
                displayname = displayname[:15]
            if len(localpart) > 15:
                localpart = localpart[:15]
            if len(domain) > 15:
                domain = domain[:15]

            domain = domain.replace('-', '_')

            self.log.debug(
                f"Bridging user {member} for {domain} externalID {localpart} externalUsername {displayname}")
            self.bot.bridged_client_from(domain, localpart.lower(), displayname)

        self.log.debug("Users bridged")
        self.log.debug("Join matrix users")

        for room_name, room_data in self.rooms.items():
            enabled = room_data.get("enabled")
            if enabled:
                room_id = RoomID(room_data.get("room_id"))
                room_users = await self.appserv.intent.get_room_members(room_id)

                for member in room_users:

                    self.log.debug(f"\tMember: {member}")

                    localpart, user_domain = self.appserv.intent.parse_user_id(UserID(member))

                    self.log.debug(f"\t\tdetails: {localpart} {user_domain}")

                    if localpart == self.config["appservice.bot_username"]:
                        self.log.debug(f"Not bridging the local appservice")
                        continue
                    elif localpart == "_discord_bot":
                        self.log.debug(f"Not bridging the discord appservice")
                        continue

                    if localpart.startswith(self.config["appservice.namespace"]):
                        self.log.debug(f"Ignoring local user {localpart}")
                        continue
                    elif localpart.startswith("_discord_"):
                        localpart = localpart.lstrip("_discord_")
                        user_domain = "discord"
                    elif localpart.startswith("freenode_"):
                        localpart = localpart.lstrip("freenode_")
                        user_domain = "freenode.org"
                    elif localpart.startswith("spring"):
                        localpart = localpart.lstrip("spring_")
                        user_domain = "springlobby"

                    try:
                        displayname = await self.appserv.intent.get_displayname(UserID(member))
                    except Exception as nf:
                        self.log.error(f"user {localpart} has no profile {nf}")
                        displayname = localpart

                    if len(displayname) > 15:
                        displayname = displayname[:15]
                    if len(localpart) > 15:
                        localpart = localpart[:15]
                    if len(user_domain) > 15:
                        self.log.debug("user domain too long")
                        user_domain = user_domain[:15]

                    self.log.debug(f"user_name = {localpart}")
                    self.log.debug(f"display_name = {displayname}")
                    self.log.debug(f"domain = {user_domain}")

                    for _, room in self.rooms.items():
                        if room["room_id"] == room_id:
                            self.log.debug(f"Join channel {room.get('name')}, user {localpart}, domain {user_domain}")
                            self.bot.join_from(room["name"], user_domain, localpart)

    async def join_matrix_room(self, room, clients):
        self.log.debug("joining matrix room join from lobby")
        self.log.debug(room)

        room_id = self.rooms[room]["room_id"]
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

                room_id = RoomID(self.rooms[room]["room_id"])
                self.log.debug(room_id)

                user = self.appserv.intent.user(user_id=UserID(matrix_id))

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

            self.bot.bridged_client_from(user_domain, user_name.lower(), display_name)  # TODO check if already bridged
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

        self.log.debug(f"room ID = {room_id}")
        self.log.debug(f"user ID = {user_id}")

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

        self.log.debug(f"User Name = {user_name}")

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

    def login(self):
        pass

    async def connect(self, server, port=8200, use_ssl=False, name=None, flags=None):
        """
        Connect to an SpringRTS Lobby server. Returns a proxy to an LobbyProtocol object.
        """
        protocol = None
        while protocol is None:
            try:
                transport, protocol = await self.loop.create_connection(lambda: LobbyProtocol(self.bot_username,
                                                                                              self.bot_password,
                                                                                              self.client_name,
                                                                                              self.client_flags
                                                                                              ),
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
