#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import nest_asyncio
import logging.config
import signal
import sys
import copy


import ruamel.yaml as yaml

from typing import Dict, List, Match, Optional, Set, Tuple, TYPE_CHECKING
from urllib.parse import quote, urlparse

from mautrix.types import (EventID, RoomID, UserID, Event, EventType, MessageEvent, MessageType,
                           MessageEventContent, StateEvent, Membership, MemberStateEventContent,
                           PresenceEvent, TypingEvent, ReceiptEvent, TextMessageEventContent)
from mautrix.appservice.appservice import AppService

from spring_lobby_client import SpringLobbyClient

with open("config.yaml", 'r') as yml_file:
    config = yaml.safe_load(yml_file)

logging.config.dictConfig(copy.deepcopy(config["logging"]))

log = logging.getLogger("matrix-spring.init")  # type: logging.Logger
log.info("Initializing matrix spring lobby bridge")


nest_asyncio.apply()
loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop



async def main():
    mebibyte = 1024 ** 2
    appserv = AppService(config["homeserver"]["address"], config["homeserver"]["domain"],
                         config["appservice"]["as_token"], config["appservice"]["hs_token"],
                         config["appservice"]["bot_username"], loop=loop, log="spring_as",
                         verify_ssl=config["homeserver"]["verify_ssl"],
                         real_user_content_key="org.jauriarts.matrix.puppet",
                         aiohttp_params={"client_max_size": config["appservice"]["max_body_size"] * mebibyte})

    hostname = config["appservice"]["hostname"]
    port = config["appservice"]["port"]

    await appserv.start(hostname, port)

    ################
    #
    # Initialization
    #
    ################

    log.info("Initialization complete, running startup actions")

    admin_list = config["appservice"]["admin_list"]
    admin_room = config["appservice"]["admin_room"]

    spring_lobby_client = SpringLobbyClient(appserv)

    await spring_lobby_client.start()

    appservice_account = await appserv.intent.whoami()
    user = appserv.intent.user(appservice_account)

    await user.ensure_joined(room_id=config['appservice']["admin_room"])

    # await user.set_presence("online")

    # location = config["homeserver"]["domain"].split(".")[0]
    # external_id = "MatrixAppService"
    # external_username = config["appservice"]["bot_username"].split("_")[1]

    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame),
                                lambda: asyncio.ensure_future(spring_lobby_client.exit(signame)))
    ################
    #
    # Matrix helper functions
    #
    ################

    # async def handle_command(body):
    #
    #     log.debug(body)
    #
    #     cmd = body[1:].split(" ")[0]
    #     args = body[1:].split(" ")[1:]
    #
    #     if cmd == "set_room_alias":
    #         if len(args) == 2:
    #             await user.add_room_alias(room_id=args[0], localpart=args[1])
    #
    #     elif cmd == "join_room":
    #         if len(args) == 1:
    #             await user.join_room(room_id_or_alias=args[0])
    #
    #     elif cmd == "leave_room":
    #         if len(args) > 0:
    #             for username in args:
    #                 await spring_lobby_client.leave_matrix_rooms(username)

        # else:
        #     await user.send_text()

    ################
    #
    # Matrix events
    #
    ################

    @appserv.matrix_event_handler
    async def handle_event(event: Event) -> None:
        log.debug("HANDLE EVENT")

        domain = config['homeserver']['domain']
        namespace = config['appservice']['namespace']

        event_type = event.get("type", "m.unknown")  # type: str
        room_id = event.get("room_id", None)  # type: Optional[RoomID]
        event_id = event.get("event_id", None)  # type: Optional[EventID]
        sender = event.get("sender", None)  # type: Optional[UserID]
        content = event.get("content", {})  # type: Dict

        log.debug(f"EVENT {event}")

        log.debug(f"EVENT TYPE: {event_type}")
        log.debug(f"EVENT ROOM_ID: {room_id}")
        log.debug(f"EVENT SENDER: {sender}")
        log.debug(f"EVENT CONTENT: {content}")

        if room_id == admin_room:
            if sender in admin_list:
                if event_type == "m.room.message":
                    body = content.get("body")
                    if body.startswith("!"):
                        pass
                        # await handle_command(body)
        else:
            if not sender.startswith(f"@{namespace}_"):
                if event_type == "m.room.message":

                    msg_type = content.get("msgtype")

                    body = content.get("body")
                    info = content.get("info")

                    if msg_type == "m.text":
                        await spring_lobby_client.say_from(sender, room_id, event_id, body)
                    elif msg_type == "m.emote":
                        await spring_lobby_client.say_from(sender, room_id, event_id, body, emote=True)
                    elif msg_type == "m.image":
                        mxc_url = event['content']['url']
                        o = urlparse(mxc_url)
                        domain = o.netloc
                        pic_code = o.path
                        url = f"https://{domain}/_matrix/media/v1/download/{domain}{pic_code}"
                        await spring_lobby_client.say_from(sender, room_id, event_id, url)

                elif event_type == "m.room.member":
                    membership = content.get("membership")

                    if membership == "join":
                        await spring_lobby_client.matrix_user_joined(sender, room_id, event_id)
                    elif membership == "leave":
                        await spring_lobby_client.matrix_user_left(sender, room_id, event_id)

    ################
    #
    # Lobby events
    #
    ################

    client_name = config['spring']['client_name']

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

    @spring_lobby_client.bot.on("denied")
    async def on_lobby_denied(message):
        return
        # if message.client.name != client_name:
        #    user = message.client.name
        #    await spring_appservice.register(user)

    @spring_lobby_client.bot.on("adduser")
    async def on_lobby_adduser(message):
        if message.client.name != client_name:
            username = message.params[0]

            if username == "ChanServ":
                return
            if username == "appservice":
                return

            await spring_lobby_client.login_matrix_account(username)

    @spring_lobby_client.bot.on("removeuser")
    async def on_lobby_removeuser(message):
        if message.client.name != client_name:
            username = message.params[0]

            if username == "ChanServ":
                return
            if username == "appservice":
                return

            await spring_lobby_client.logout_matrix_account(username)

    @spring_lobby_client.bot.on("accepted")
    async def on_lobby_accepted(message):
        log.debug(f"message Accepted {message}")
        await spring_lobby_client.bridge_logged_users()

    @spring_lobby_client.bot.on("failed")
    async def on_lobby_failed(message):
        log.debug(f"message FAILED {message}")

    log.info("Startup actions complete, now running forever")
    loop.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
