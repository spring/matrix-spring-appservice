#!/usr/bin/env python
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
import logging.config
import signal

import copy
from typing import Optional, Dict
from urllib.parse import urlparse

from mautrix.bridge import BaseBridgeConfig
from mautrix.client.api.types import PresenceState
from mautrix.errors import MForbidden
from mautrix.types import (EventID, RoomID, UserID, Event, EventType, MessageEvent, MessageType,
                           MessageEventContent, StateEvent, Membership, MemberStateEventContent,
                           PresenceEvent, TypingEvent, ReceiptEvent, TextMessageEventContent)
from mautrix.appservice import AppService

from config import Config

from spring_lobby_client import SpringLobbyClient


class Matrix:
    az: AppService
    sl: SpringLobbyClient
    config: 'BaseBridgeConfig'

    user_id_prefix: str
    user_id_suffix: str

    def __init__(self, az, sl, config):
        self.log = logging.getLogger("matrix.events")
        self.az = az
        self.sl = sl
        self.config = config

    async def handle_message(self, room_id: RoomID, user_id: UserID, message: MessageEventContent,
                             event_id: EventID) -> None:

        self.log.debug(f"message \"{message}\" from {user_id} to {room_id}:")

        if str(message.msgtype) == "m.text":
            await self.sl.say_from_matrix(user_id, room_id, event_id, message.body)
        elif str(message.msgtype) == "m.emote":
            await self.sl.say_from_matrix(user_id, room_id, event_id, message.body, emote=True)
        elif str(message.msgtype) == 'm.image':
            mxc_url = message.url
            o = urlparse(mxc_url)
            domain = o.netloc
            pic_code = o.path
            url = f"https://{domain}/_matrix/media/v1/download/{domain}{pic_code}"
            await self.sl.say_from_matrix(user_id, room_id, event_id, url)

        elif str(message.msgtype) == "m.sticker":
            mxc_url = message.url
            o = urlparse(mxc_url)
            domain = o.netloc
            pic_code = o.path
            url = f"https://{domain}/_matrix/media/v1/download/{domain}{pic_code}"
            await self.sl.say_from_matrix(user_id, room_id, event_id, url)

        else:
            self.log.debug(f"Unhandled message type {message.msgtype}")

    async def handle_event(self, event: Event) -> None:

        self.log.debug("Handle event")

        domain = self.config['homeserver.domain']
        namespace = self.config['appservice.namespace']

        event_type = event.get("type", "m.unknown")  # type: str
        room_id = event.get("room_id", None)  # type: Optional[RoomID]
        event_id = event.get("event_id", None)  # type: Optional[EventID]
        sender = event.get("sender", None)  # type: Optional[UserID]
        content = event.get("content", {})  # type: Dict

        self.log.debug(f"Event {event}")

        self.log.debug(f"Event type: {event.type}")
        self.log.debug(f"Event room_id: {room_id}")
        self.log.debug(f"Event sender: {sender}")
        self.log.debug(f"Event content: {content}")

        if event.type == EventType.ROOM_MEMBER:
            event: StateEvent
            prev_content = event.unsigned.prev_content or MemberStateEventContent()
            prev_membership = prev_content.membership if prev_content else Membership.JOIN

            if event.content.membership == Membership.LEAVE:
                if event.sender == event.state_key:
                    await self.sl.matrix_user_left(UserID(event.state_key), event.room_id, event.event_id)
            elif event.content.membership == Membership.JOIN:
                if prev_membership != Membership.JOIN:
                    await self.sl.matrix_user_joined(UserID(event.state_key), event.room_id, event.event_id)

        elif event.type in (EventType.ROOM_MESSAGE, EventType.STICKER):
            event: MessageEvent
            if event.type != EventType.ROOM_MESSAGE:
                event.content.msgtype = MessageType(str(event.type))
            await self.handle_message(event.room_id, event.sender, event.content, event.event_id)

    async def wait_for_connection(self) -> None:
        self.log.info("Ensuring connectivity to homeserver")
        errors = 0
        while True:
            try:
                await self.az.intent.whoami()
                break
            except MForbidden:
                raise
            except Exception:
                errors += 1
                if errors <= 6:
                    self.log.exception("Connection to homeserver failed, retrying in 10 seconds")
                    await asyncio.sleep(10)
                else:
                    raise

    async def init_as_bot(self) -> None:
        self.log.debug("Initializing appservice bot")
        displayname = self.config["appservice.bot_displayname"]
        if displayname:
            try:
                await self.az.intent.set_displayname(
                    displayname if displayname != "remove" else "")
            except Exception:
                self.log.exception("Failed to set bot displayname")

        avatar = self.config["appservice.bot_avatar"]
        if avatar:
            try:
                await self.az.intent.set_avatar_url(avatar if avatar != "remove" else "")
            except Exception:
                self.log.exception("Failed to set bot avatar")


async def main():

    config = Config("config.yaml", None, None)
    config.load()

    logging.config.dictConfig(copy.deepcopy(config["logging"]))

    log = logging.getLogger("appservice.main")  # type: logging.Logger

    log.info("Initializing matrix spring lobby bridge")

    ################
    #
    # Initialization
    #
    ################

    mebibyte = 1024 ** 2

    appserv = AppService(server=config["homeserver.address"],
                         domain=config["homeserver.domain"],
                         verify_ssl=config["homeserver.verify_ssl"],

                         as_token=config["appservice.as_token"],
                         hs_token=config["appservice.hs_token"],

                         bot_localpart=config["appservice.bot_username"],

                         log=log,
                         loop=loop,

                         real_user_content_key="org.jauriarts.appservice.puppet",
                         aiohttp_params={"client_max_size": config["appservice.max_body_size"] * mebibyte})

    hostname = config["appservice.hostname"]
    port = config["appservice.port"]

    spring_lobby_client = SpringLobbyClient(appserv, config, loop=loop)

    await appserv.start(hostname, port)
    await spring_lobby_client.start()


    ################
    #
    # Lobby events
    #
    ################

    client_name = config['spring']['client_name']

    log.info("Startup actions complete, now running forever")

    @spring_lobby_client.bot.on("clients")
    async def on_lobby_clients(message):
        log.debug(f"on_lobby_clients {message}")
        if message.client.name != client_name:
            channel = message.params[0]
            clients = message.params[1:]
            await spring_lobby_client.join_matrix_room(channel, clients)

    @spring_lobby_client.bot.on("joined")
    async def on_lobby_joined(message, user, channel):
        log.debug(f"LOBBY JOINED user: {user.username} room: {channel}")
        if user.username != "appservice":
            await spring_lobby_client.join_matrix_room(channel, [user.username])

    @spring_lobby_client.bot.on("left")
    async def on_lobby_left(message, user, channel):
        log.debug(f"LOBBY LEFT user: {user.username} room: {channel}")

        if channel.startswith("__battle__"):
            return

        if user.username == "appservice":
            return

        await spring_lobby_client.leave_matrix_room(channel, [user.username])

    @spring_lobby_client.bot.on("said")
    async def on_lobby_said(message, user, target, text):
        if message.client.name == client_name:
            await spring_lobby_client.said(user, target, text)

    @spring_lobby_client.bot.on("saidex")
    async def on_lobby_saidex(message, user, target, text):
        if message.client.name == client_name:
            await spring_lobby_client.saidex(user, target, text)

    # @spring_lobby_client.bot.on("denied")
    # async def on_lobby_denied(message):
    #     return
    #     # if message.client.name != client_name:
    #     #    user = message.client.name
    #     #    await spring_appservice.register(user)

    # @spring_lobby_client.bot.on("adduser")
    # async def on_lobby_adduser(message):
    #     if message.client.name != client_name:
    #         username = message.params[0]
    #
    #         if username == "ChanServ":
    #             return
    #         if username == "appservice":
    #             return
    #
    #         await spring_lobby_client.login_matrix_account(username)

    # @spring_lobby_client.bot.on("removeuser")
    # async def on_lobby_removeuser(message):
    #     if message.client.name != client_name:
    #         username = message.params[0]
    #
    #         if username == "ChanServ":
    #             return
    #         if username == "appservice":
    #             return
    #
    #         await spring_lobby_client.logout_matrix_account(username)

    @spring_lobby_client.bot.on("accepted")
    async def on_lobby_accepted(message):
        log.debug(f"message Accepted {message}")
        await spring_lobby_client.sync_matrix_users()

    @spring_lobby_client.bot.on("failed")
    async def on_lobby_failed(message):
        log.debug(f"message FAILED {message}")

    matrix = Matrix(appserv, spring_lobby_client, config)

    appserv.matrix_event_handler(matrix.handle_event)

    await matrix.wait_for_connection()
    await matrix.init_as_bot()

    appservice_account = await appserv.intent.whoami()
    user = appserv.intent.user(appservice_account)

    await appserv.intent.set_presence(PresenceState.ONLINE)

    # location = config["homeserver"]["domain"].split(".")[0]
    # external_id = "MatrixAppService"
    # external_username = config["appservice"]["bot_username"].split("_")[1]

    rooms = config["bridge"]["rooms"]

    for room in rooms:

        enabled = config["bridge.rooms"][room]["enabled"]
        room_id = config["bridge.rooms"][room]["room_id"]
        room_alias = f"{config['appservice.namespace']}_{room}"

        if enabled is True:
            await user.ensure_joined(room_id=room_id)
            await appserv.intent.add_room_alias(room_id=RoomID(room_id), alias_localpart=room_alias, override=True)
        else:
            # await appserv.intent.remove_room_alias(alias_localpart=room_alias)
            try:
                await user.leave_room(room_id=room_id)
            except Exception as e:
                log.debug(f"Failed to leave room, not previously joined: {e}")

    appserv.ready = True
    log.info("Initialization complete, running startup actions")

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
                                lambda: asyncio.ensure_future(spring_lobby_client.exit(signame)))


if __name__ == "__main__":
    loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop
    loop.run_until_complete(main())
    loop.run_forever()
