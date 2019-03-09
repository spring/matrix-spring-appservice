#!/usr/bin/env python3
# -*- coding: future_fstrings -*-
# -*- coding: utf-8 -*-

import asyncio
import logging.config
import signal
import sys
import copy

from asyncblink import signal as as_signal

from collections import defaultdict

import yaml

from typing import Dict, List, Match, Optional, Set, Tuple, TYPE_CHECKING
from urllib.parse import quote, urlparse

from matrix_client.api import MatrixHttpApi

from mautrix_appservice import AppService
from m_types import MatrixEvent, MatrixEventID, MatrixRoomID, MatrixUserID

from asyncspring import spring

with open("config.yaml", 'r') as yml_file:
    config = yaml.load(yml_file)

logging.config.dictConfig(copy.deepcopy(config["logging"]))
log = logging.getLogger("matrix-spring.init")  # type: logging.Logger
log.debug("Initializing matrix-spring")

loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop

state_store = "state_store.json"

mebibyte = 1024 ** 2

matrix_api = MatrixHttpApi(config["homeserver"]["address"])

appserv = AppService(config["homeserver"]["address"], config["homeserver"]["domain"],
                     config["appservice"]["as_token"], config["appservice"]["hs_token"],
                     config["appservice"]["bot_username"], log="spring_as", loop=loop,
                     verify_ssl=config["homeserver"]["verify_ssl"], state_store=state_store,
                     real_user_content_key="com.springrts.matrix.puppet",
                     aiohttp_params={"client_max_size": config["appservice"]["max_body_size"] * mebibyte})

DOMAINS = ["[matrix]", "[jauriarts]", "[springrts]"]


def get_matrix_room_id(room):
    room_id = matrix_api.get_room_id(room)
    return room_id


async def get_matrix_room_alias(room):
    room_alias = await appserv.intent.client.request(
        "GET",
        f"/rooms/{quote(room, safe='')}/state/m.room.aliases/{config['homeserver']['domain']}")

    return room_alias


def remove_matrix_room(room):
    matrix_api.remove_room_alias(f"#spring_{room}:{config['homeserver']['domain']}")


async def get_users_in_matrix_rooms():
    rooms = await appserv.intent.get_joined_rooms()
    log.debug(rooms)
    spring_users_in_room = dict()

    for room in rooms:
        matrix_users = await appserv.intent.get_room_members(room)
        log.debug(matrix_users)
        for user in matrix_users:
            if not user.startswith("@spring"):
                log.debug(user)
                spring_users_in_room[user] = room

    return spring_users_in_room


class SpringAppService(object):

    def __init__(self):

        # await appserv.intent.add_room_alias(room_id="!VDtYyDdWFgqjyYVhpZ:jauriarts.org", localpart="spring_main"))

        self.bot = None
        self.rooms = None
        self.user_rooms = defaultdict(list)
        self.user_info = dict()
        self.appservice = None

    async def run(self):

        log.debug("RUN")

        appservice_account = await appserv.intent.whoami()
        self.appservice = appserv.intent.user(appservice_account)
        await self.appservice.set_presence("online")

        server = config["spring"]["address"]
        port = config["spring"]["port"]
        use_ssl = config["spring"]["ssl"]
        name = config["spring"]["client_name"]

        self.bot = await spring.connect(server=server,
                                        port=port,
                                        use_ssl=use_ssl,
                                        name=name)

        self.rooms = config['appservice']['bridge']

        log.debug(self.rooms)

        for room in self.rooms:
            for room_name, room_id in room.items():
                channel = "#{}".format(room_name)
                self.bot.channels_to_join.append(channel)

        self.bot.login(config["spring"]["bot_username"],
                       config["spring"]["bot_password"])

    async def leave_all_matrix_rooms(self, username):
        user = appserv.intent.user(username)
        for room in await user.get_joined_rooms():
            await user.leave_room(room)

    async def login_matrix_account(self, username):
        matrix_id = f"@spring_{username.lower()}:{config['homeserver']['domain']}"
        user = appserv.intent.user(matrix_id)

        task = [user.set_presence("online"),
                user.set_display_name(username)]

        loop.run_until_complete(asyncio.gather(*task, loop=loop))

    async def logout_matrix_account(self, username):
        matrix_id = f"@spring_{username.lower()}:{config['homeserver']['domain']}"
        user = appserv.intent.user(matrix_id)

        rooms = await user.get_joined_rooms()

        for room_id in rooms:
            await user.leave_room(room_id=room_id)

        await user.set_presence("offline")

    async def clean_matrix_rooms(self):
        for room in self.rooms:
            for channel, room_id in room.items():
                members = await appserv.intent.get_room_members(room_id=room_id)

                for member in members:
                    if member.startswith("@spring_"):
                        user = appserv.intent.user(user=member)
                        await user.leave_room(room_id)

    async def bridge_logged_users(self):

        for room in self.rooms:
            for channel, room_id in room.items():
                members = await appserv.intent.get_room_members(room_id=room_id)
                for user_id in members:
                    if user_id != "@spring:jauriarts.org" and user_id != "@_discord_bot:jauriarts.org" and not user_id.startswith("@spring_"):

                        self.user_rooms[user_id].append(room)

                        domain = user_id.split(":")[1]
                        user_name = user_id.split(":")[0][1:]

                        user = await appserv.intent.get_member_info(room_id=room_id, user_id=user_id)

                        display_name = user.get("displayname")

                        if display_name is None:
                            display_name = user_name

                        self.user_info[user_id] = dict(domain=domain,
                                                       user_name=user_name,
                                                       display_name=display_name)

        bridge_signal = as_signal('bridg-signal')
        join_sginal = as_signal('join-signal')

        bridge_signal.connect(self.bridged_client)
        join_sginal.connect(self.join_from)

        for user_id, rooms in self.user_rooms.items():

            display_name = self.user_info[user_id].get("display_name")
            domain = self.user_info[user_id].get("domain")
            user_name = self.user_info[user_id].get("user_name")

            if user_name.startswith("_discord"):
                domain = "discord"
                user_name = user_name.lstrip("_discord_")

            elif user_name.startswith("freenode"):
                domain = "freenode.org"
                user_name = user_name.lstrip("freenode_")

            if display_name:
                display_name = display_name.lstrip('@')
                display_name = display_name.replace('-', '_')
                if len(display_name) > 15:
                    display_name = display_name[:15]
            else:
                display_name = "none"


            bridge_signal.send("initial-bridging", domain=domain, user_name=user_name, display_name=display_name)

            for room in rooms:
                for channel, room_id in room.items():
                    join_sginal.send("initial-joining", channel=channel, domain=domain, user_name=user_name)

    async def bridged_client(self, sender, domain, user_name, display_name):
        self.bot.bridged_client_from(domain, user_name, display_name)

    async def join_from(self, sender, channel, domain, user_name):
        self.bot.join_from(channel, domain, user_name)

    async def join_matrix_room(self, room, clients):
        room_alias = f"#spring_{room.lower()}:{config['homeserver']['domain']}"

        for client in clients:
            if client != "appservice":
                if not any(domain in client for domain in DOMAINS):
                    matrix_id = f"@spring_{client.lower()}:{config['homeserver']['domain']}"
                    user = appserv.intent.user(matrix_id)

                    await user.join_room(room_alias)

    async def leave_matrix_room(self, room, clients):
        for client in clients:
            if client != "spring":
                matrix_id = f"@spring_{client}:{config['homeserver']['domain']}"
                room_alias = f"#spring_{room}:{config['homeserver']['domain']}"

                user = appserv.intent.user(matrix_id)
                room_id = get_matrix_room_id(room_alias)

                await user.leave_room(room_id=room_id)

    async def create_matrix_room(self, room):
        room_alias = f"#spring_{room}:{config['homeserver']['domain']}"
        try:
            room_id = await appserv.intent.create_room(alias=room_alias, is_public=True)
            await appserv.intent.join_room(room_id)
            log.debug(f"room created = {room_id}")
        except Exception as e:
            log.debug(e)

    async def said(self, user, room, message):
        matrix_id = f"@spring_{user.lower()}:{config['homeserver']['domain']}"
        room_alias = f"#spring_{room}:{config['homeserver']['domain']}"

        if matrix_id == "@spring_glenda:jaurarts.org":
            return

        room_id = get_matrix_room_id(room_alias)
        user = appserv.intent.user(matrix_id)
        log.debug("SEND MESSAGE TO THE MATRIX")

        await user.send_text(room_id, message)

    async def saidex(self, user, room, message):
        matrix_id = f"@spring_{user.lower()}:{config['homeserver']['domain']}"
        room_alias = f"#spring_{room}:{config['homeserver']['domain']}"

        if matrix_id == "@spring_glenda:jaurarts.org":
            return

        room_id = get_matrix_room_id(room_alias)
        user = appserv.intent.user(matrix_id)

        await user.send_emote(room_id, message)

    async def matrix_user_joined(self, user_id, room_id, event_id=None):

        if user_id.startswith("@spring_"):
            return

        room_alias = await get_matrix_room_alias(room_id)

        room_list = room_alias["aliases"]

        channel = None
        for room in room_list:
            if room.startswith("#spring_"):
                channel = room.split("_")[1].split(":")[0]

        domain = user_id.split(":")[1]
        user_name = user_id.split(":")[0][1:]

        if user_name.startswith("_discord"):
            domain = "discord"
            user_name = user_name.lstrip("_discord")

        if user_name.startswith("freenode"):
            domain = "freenode.org"
            user_name = user_name.lstrip("freenode_")

        user = await appserv.intent.get_member_info(room_id=room_id, user_id=user_id)

        display_name = user.get("displayname")

        if display_name:
            display_name = display_name.lstrip('@')
            display_name = display_name.replace('-', '_')
            if len(display_name) > 15:
                display_name = display_name[:15]
        else:
            display_name = "none"

        if event_id:
            await self.appservice.mark_read(room_id=room_id, event_id=event_id)

        self.bot.bridged_client_from(domain, user_name, display_name)
        self.bot.join_from(channel, domain, user_name)

    async def matrix_user_left(self, user_id, room_id, event_id):

        if user_id.startswith("@spring_"):
            return

        user = await appserv.intent.get_member_info(room_id=room_id, user_id=user_id)

        display_name = user.get("displayname")
        domain = user_id.split(":")[1]
        user_name = user_id.split(":")[0][1:]

        if user_name.startswith("_discord"):
            domain = "discord"
            user_name = user_name.lstrip("_discord_")

        if display_name is None:
            display_name = user_name

        await self.appservice.mark_read(room_id=room_id, event_id=event_id)

        self.bot.leave_from("test", domain, display_name)
        self.bot.un_bridged_client_from(domain, display_name)

    async def say_from(self, user_id, room_id, event_id, body, emote=False):

        if user_id.startswith("@spring_"):
            return

        room_alias = await get_matrix_room_alias(room_id)

        room_list = room_alias["aliases"]

        channel = None
        for room in room_list:
            if room.startswith("#spring_"):
                channel = room.split("_")[1].split(":")[0]

        if channel is None:
            log.info("no chanel found in room_list")
        else:
            user_name = user_id.split(":")[0][1:]
            domain = user_id.split(":")[1]

            if user_name.startswith("_discord"):
                domain = "discord"
                user_name = user_name.lstrip("_discord_")

            await self.appservice.mark_read(room_id=room_id, event_id=event_id)
            self.bot.say_from(user_name, domain, channel, body)

    async def exit(self, signal_name):
        await self.clean_matrix_rooms()
        log.debug(f"QUIT {signal_name}")
        sys.exit(0)


def main():

    hostname = config["appservice"]["hostname"]
    port = config["appservice"]["port"]

    with appserv.run(hostname, port) as start:

        ################
        #
        # Initialization
        #
        ################

        log.info("Initialization complete, running startup actions")

        admin_list = config["appservice"]["admin_list"]
        admin_room = config["appservice"]["admin_room"]

        spring_appservice = SpringAppService()

        tasks = (spring_appservice.run(), start)
        loop.run_until_complete(asyncio.gather(*tasks, loop=loop))

        appservice_account = loop.run_until_complete(appserv.intent.whoami())
        user = appserv.intent.user(appservice_account)
        loop.run_until_complete(user.set_presence("online"))

        # location = config["homeserver"]["domain"].split(".")[0]
        # external_id = "MatrixAppService"
        # external_username = config["appservice"]["bot_username"].split("_")[1]

        for signame in ('SIGINT', 'SIGTERM'):
            loop.add_signal_handler(getattr(signal, signame),
                                    lambda: asyncio.ensure_future(spring_appservice.exit(signame)))

        ################
        #
        # Matrix helper functions
        #
        ################

        async def remove_ghost():
            users = await get_users_in_matrix_rooms()

            log.debug(users)
            # spring_appservice.logout_matrix_account()

        async def handle_command(body):

            log.debug(body)

            cmd = body[1:].split(" ")[0]
            args = body[1:].split(" ")[1:]

            if cmd == "set_room_alias":
                if len(args) == 2:
                    await user.add_room_alias(room_id=args[0], localpart=args[1])

            elif cmd == "join_room":
                if len(args) == 1:
                    await user.join_room(room_id=args[0])

            elif cmd == "leave_room":
                if len(args) == 1:
                    await user.leave_room(room_id=args[0])

            elif cmd == "remove_ghost":
                if len(args) == 0:
                    await remove_ghost()

            else:
                await user.send_text()

        ################
        #
        # Matrix events
        #
        ################

        @appserv.matrix_event_handler
        async def handle_event(event: MatrixEvent) -> None:

            log.debug("HANDLE EVENT")

            event_type = event.get("type", "m.unknown")  # type: str
            room_id = event.get("room_id", None)  # type: Optional[MatrixRoomID]
            event_id = event.get("event_id", None)  # type: Optional[MatrixEventID]
            sender = event.get("sender", None)  # type: Optional[MatrixUserID]
            content = event.get("content", {})  # type: Dict

            log.debug("EVENT TYPE: {}".format(event_type))
            log.debug("EVENT ROOM_ID: {}".format(room_id))
            log.debug("EVENT SENDER: {}".format(sender))
            log.debug("EVENT CONTENT: {}".format(content))

            if room_id == admin_room:
                if sender in admin_list:
                    if event_type == "m.room.message":
                        body = content.get("body")
                        if body.startswith("!"):
                            await handle_command(body)
            else:
                if not sender.startswith("@spring_"):
                    if event_type == "m.room.message":

                        msg_type = content.get("msgtype")

                        body = content.get("body")
                        info = content.get("info")

                        if msg_type == "m.text":
                            await spring_appservice.say_from(sender, room_id, event_id, body)
                        elif msg_type == "m.emote":
                            await spring_appservice.say_from(sender, room_id, event_id, body, emote=True)
                        elif msg_type == "m.image":
                            mxc_url = event['content']['url']
                            o = urlparse(mxc_url)
                            domain = o.netloc
                            pic_code = o.path
                            url = "https://{0}/_matrix/media/v1/download/{0}{1}".format(domain, pic_code)
                            await spring_appservice.say_from(sender, room_id, event_id, url)

                    elif event_type == "m.room.member":
                        membership = content.get("membership")

                        if membership == "join":
                            await spring_appservice.matrix_user_joined(sender, room_id, event_id)
                        elif membership == "leave":
                            await spring_appservice.matrix_user_left(sender, room_id, event_id)

        ################
        #
        # Spring events
        #
        ################

        client_name = config['spring']['client_name']

        @spring_appservice.bot.on("clients")
        async def on_lobby_clients(message):
            if message.client.name == client_name:
                channel = message.params[0]
                clients = message.params[1:]
                await spring_appservice.join_matrix_room(channel, clients)

        @spring_appservice.bot.on("joined")
        async def on_lobby_joined(message, user, channel):
            if user.username != "appservice":
                await spring_appservice.join_matrix_room(channel, [user.username])

        @spring_appservice.bot.on("left")
        async def on_lobby_left(message, user, channel, reason):
            if user.username != "appservice":
                await spring_appservice.leave_matrix_room(channel, [user.username])

        @spring_appservice.bot.on("said")
        async def on_lobby_said(message, user, target, text):
            if message.client.name == client_name:
                await spring_appservice.said(user, target, text)

        @spring_appservice.bot.on("saidex")
        async def on_lobby_saidex(message, user, target, text):
            if message.client.name == client_name:
                await spring_appservice.saidex(user, target, text)

        @spring_appservice.bot.on("denied")
        async def on_lobby_denied(message):
            if message.client.name != client_name:
                user = message.client.name
                # await spring_appservice.register(user)

        @spring_appservice.bot.on("adduser")
        async def on_lobby_adduser(message):
            if message.client.name == client_name:
                username = message.params[0]

                if username == "ChanServ":
                    return
                if username == "appservice":
                    return

                await spring_appservice.login_matrix_account(username)

        @spring_appservice.bot.on("removeuser")
        async def on_lobby_removeuser(message):
            if message.client.name == client_name:
                username = message.params[0]

                if username == "ChanServ":
                    return
                if username == "appservice":
                    return

                await spring_appservice.logout_matrix_account(username)

        @spring_appservice.bot.on("accepted")
        async def on_lobby_accepted(message):
            if message.client.name == client_name:
                await spring_appservice.bridge_logged_users()

        log.info("Startup actions complete, now running forever")
        loop.run_forever()


if __name__ == "__main__":
    main()
