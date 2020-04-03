import asyncio
import logging
import sys

from asyncblink import signal as asignal

from collections import defaultdict

from asyncspring.lobby import LobbyProtocol, LobbyProtocolWrapper, connections
from ruamel import yaml
log = logging.getLogger("matrix-spring.lobby-client")  # type: logging.Logger


class SpringLobbyClient(object):

    def __init__(self, appserv):

        self.bot = None
        self.rooms = None
        self.user_rooms = defaultdict(list)
        self.user_info = dict()
        self.appserv = appserv
        self.appservice = None
        self.presence_timmer = None
        self.bot_username = None
        self.bot_password = None

        with open("config.yaml", 'r') as yml_file:
            self.config = yaml.safe_load(yml_file)

        self.loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop



    async def start(self):

        log.debug("RUN")

        appservice_account = await self.appserv.intent.whoami()
        self.appservice = self.appserv.intent.user(appservice_account)
        # await self.appservice.set_presence("online")

        server = self.config["spring"]["address"]
        port = self.config["spring"]["port"]
        use_ssl = self.config["spring"]["ssl"]
        name = self.config["spring"]["client_name"]
        flags = self.config["spring"]["client_flags"]

        self.bot = await self.connect(server=server,
                                      port=port,
                                      use_ssl=use_ssl,
                                      name=name,
                                      flags=flags)

        self.rooms = self.config['appservice']['bridge']

        log.debug("### CONFIG ROOMS ###")

        for room_name, room_data in self.rooms.items():
            channel = f"#{room_name}"
            room_id = room_data["room_id"],
            room_enabled = room_data["enabled"]

            log.info(f"{room_enabled} channel : {channel} room_name : {room_name} room_id : {room_id}")
            if room_enabled:
                self.bot.channels_to_join.append(channel)
                await self.appservice.join_room(room_id[0])

        self.bot_username = self.config["spring"]["bot_username"]
        self.bot_password = self.config["spring"]["bot_password"]

        self.bot.login(self.bot_username,
                       self.bot_password)

    # def _presence_timer(self, user):
    #     log.debug(f"SET presence timmer for user : {user}")
    #
    #     task = [user.set_presence("online"),
    #             user.set_display_name(user)]
    #
    #     loop.run_until_complete(asyncio.gather(*task, loop=loop))

    async def leave_matrix_rooms(self, username):
        user = self.appserv.intent.user(username)
        for room in await user.get_joined_rooms():
            await user.leave_room(room)

    async def login_matrix_account(self, user_name):
        domain = self.config['homeserver']['domain']
        namespace = self.config['appservice']['namespace']
        matrix_id = f"@{namespace}_{user_name.lower()}:{domain}"
        user = self.appserv.intent.user(matrix_id)

        task = [user.set_presence("online"), user.set_display_name(user_name)]

        await asyncio.gather(*task)

        # self.presence_timmer = asyncio.get_event_loop().call_later(58, self._presence_timer, user)

        self.bot.bridged_client_from(domain, user_name.lower, user_name)

    async def logout_matrix_account(self, user_name):
        domain = self.config['homeserver']['domain']
        namespace = self.config['appservice']['namespace']
        matrix_id = f"@{namespace}_{user_name.lower()}:{domain}"
        user = self.appserv.intent.user(matrix_id)

        rooms = await user.get_joined_rooms()

        for room_id in rooms:
            await user.leave_room(room_id=room_id)

        await user.set_presence("offline")
        self.presence_timmer.cancel()
        self.bot.un_bridged_client_from(domain, user_name)

    async def clean_matrix_rooms(self):

        for room_name, room_data in self.rooms.items():
            channel = room_name
            room_id = room_data["room_id"]
            enabled = room_data["enabled"]

            log.debug(f"removing logged users from {channel}")

            members = await self.appserv.intent.get_room_members(room_id=room_id)

            for member in members:
                namespace = self.config['appservice']['namespace']
                if member.startswith(f"@{namespace}_"):
                    log.debug(f"user {member}")
                    user = self.appserv.intent.user(user=member)
                    await user.leave_room(room_id)

    async def bridge_logged_users(self):

        for room_name, room_data in self.rooms.items():
            channel = room_name
            room_id = room_data["room_id"]
            enabled = room_data["enabled"]

            if enabled:
                log.debug("############### ROOM ENABLED ###############")
                log.debug(f"channel : {channel}")
                log.debug(f"room_id : {room_id}")

                members = await self.appservice.get_room_members(room_id=room_id)

                domain = self.config['homeserver']['domain']
                namespace = self.config['appservice']['namespace']

                for user_id in members:
                    if user_id == f"@appservice:{domain}":
                        continue
                    elif user_id.startswith(f"@{namespace}_"):
                        continue
                    else:
                        self.user_rooms[user_id].append({"channel": channel, "room_id": room_id})

                        domain = user_id.split(":")[1]
                        user_name = user_id.split(":")[0][1:]

                        user = None

                        while user is None:
                            log.debug("Getting member info ...")
                            user = await self.appserv.intent.get_member_info(room_id=room_id, user_id=user_id)

                        display_name = user.get("displayname")
                        log.debug(user_id)
                        log.debug(display_name)

                        self.user_info[user_id] = dict(domain=domain,
                                                       user_name=user_name,
                                                       display_name=display_name)

            else:

                log.debug("############### ROOM DISABLED ###############")
                log.debug(f"channel : {channel}")
                log.debug(f"room_id : {room_id}")

            log.debug("#############################################")
            log.debug("")

        log.debug("############### INITIAL JOINS ###############")

        for user_id, rooms in self.user_rooms.items():

            display_name = self.user_info[user_id].get("display_name")
            domain = self.user_info[user_id].get("domain")
            user_name = self.user_info[user_id].get("user_name")

            if user_name == self.config['spring']['bot_username'] or user_name == '_discord_bot' or user_name == 'spring':
                continue

            log.debug(f"user_name = {user_name}")
            log.debug(f"display_name = {display_name}")
            log.debug(f"domain = {domain}")

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

            log.debug(f"user_name = {user_name}")
            log.debug(f"display_name = {display_name}")
            log.debug(f"domain = {domain}")

            log.debug(f"Bridging user {user_name}, domain {domain}. displayname {display_name}")
            self.bot.bridged_client_from(domain, user_name, display_name)

            for room in rooms:
                channel = room["channel"]
                log.debug(f"Join channel {channel}, user {user_name}, domain {domain}")
                self.bot.join_from(channel, domain, user_name)

            log.debug("##############################")

    async def join_matrix_room(self, room, clients):

        room_id = self.rooms[room]["room_id"]
        log.debug(room_id)

        for client in clients:
            if client != "appservice":
                domain = self.config['homeserver']['domain']
                namespace = self.config['appservice']['namespace']
                matrix_id = f"@{namespace}_{client.lower()}:{domain}"
                user = self.appserv.intent.user(matrix_id)

                await user.join_room_by_id(room_id=room_id)

    async def leave_matrix_room(self, room, clients):
        log.debug("leaving matrix room left from lobby")
        log.debug(room)
        for client in clients:
            log.debug(client)
            if client != "spring":
                log.debug(f"CLIENT {client}")

                domain = self.config['homeserver']['domain']
                namespace = self.config['appservice']['namespace']

                matrix_id = f"@{namespace}_{client.lower()}:{domain}"
                log.debug(matrix_id)

                room_id = self.rooms[room]["room_id"]
                log.debug(room_id)

                user = self.appserv.intent.user(matrix_id)

                log.debug(user)
                await user.leave_room(room_id=room_id)

        log.debug("succes leaved matrix room left from lobby")

    async def create_matrix_room(self, room):

        domain = self.config['homeserver']['domain']
        namespace = self.config['appservice']['namespace']

        room_alias = f"#{namespace}_{room}:{domain}"
        try:
            room_id = await self.appserv.intent.create_room(alias=room_alias, is_public=True)
            await self.appserv.intent.join_room(room_id)
            log.debug(f"room created = {room_id}")
        except Exception as e:
            log.debug(e)

    async def said(self, user, room, message):

        domain = self.config['homeserver']['domain']
        namespace = self.config['appservice']['namespace']

        matrix_id = f"@{namespace}_{user.lower()}:{domain}"

        room_id = self.rooms[room]["room_id"]

        user = self.appserv.intent.user(matrix_id)

        await user.send_text(room_id, message)

    async def saidex(self, user, room, message):

        domain = self.config['homeserver']['domain']
        namespace = self.config['appservice']['namespace']

        matrix_id = f"@{namespace}_{user.lower()}:{domain}"

        room_id = self.rooms[room]["room_id"]

        user = self.appserv.intent.user(matrix_id)

        await user.send_emote(room_id, message)

    async def matrix_user_joined(self, user_id, room_id, event_id=None):

        hs_domain = self.config['homeserver']['domain']
        namespace = self.config['appservice']['namespace']

        if user_id.startswith(f"@{namespace}_") or user_id == f"@appservice:{hs_domain}":
            return

        channel = None
        for key in self.rooms:
            if self.rooms[key]["room_id"] == room_id:
                channel = key

        user_name = None
        user_domain = None

        if user_id not in self.user_info.keys():
            if user_id.startswith("@_discord_"):
                user_domain = "discord"
                user_name = user_id.lstrip("@_discord_")
                user_name = user_name.rstrip(":springrts.com")

            elif user_id.startswith("@freenode_"):
                user_domain = "freenode.org"
                user_name = user_id.lstrip("@freenode_")
                user_name = user_name.rstrip(":matrix.org")

            self.user_info[user_id] = dict(domain=user_domain,
                                           user_name=user_name,
                                           display_name=user_name)

        else:

            # display_name = self.user_info[user_id].get("display_name")
            user_domain = self.user_info[user_id].get("domain")
            user_name = self.user_info[user_id].get("user_name")

        if event_id:
            await self.appservice.mark_read(room_id=room_id, event_id=event_id)

        log.debug(channel)

        if user_name and user_domain:
            display_name = self.user_info[user_id].get("display_name")
            self.bot.bridged_client_from(user_domain, user_name, display_name)
            self.bot.join_from(channel, user_domain, user_name)

    async def matrix_user_left(self, user_id, room_id, event_id):
        log.debug("MATRIX USER LEAVES")

        if user_id not in self.user_info.keys():
            return

        domain = self.config['homeserver']['domain']
        namespace = self.config['appservice']['namespace']

        if user_id.startswith(f"@{namespace}_") or user_id == f"@appservice:{domain}":
            return

        channel = None
        for key in self.rooms:
            if self.rooms[key]["room_id"] == room_id:
                channel = key

        display_name = self.user_info[user_id].get("display_name")
        domain = self.user_info[user_id].get("domain")
        user_name = self.user_info[user_id].get("user_name")

        if event_id:
            await self.appservice.mark_read(room_id=room_id, event_id=event_id)

        log.debug(channel)

        self.bot.leave_from(channel, domain, display_name)

        log.debug("MATRIX USER LEAVES SUSSCESS")

    async def say_from(self, user_id, room_id, event_id, body, emote=False):

        namespace = self.config['appservice']['namespace']

        if user_id.startswith(f"@{namespace}"):
            return

        log.debug(self.rooms)
        channel = None
        for room_name, room_data in self.rooms.items():
            stored_room_id = room_data["room_id"]
            enabled = room_data["enabled"]

            if enabled == str('True'):
                log.debug(f"{stored_room_id} {room_id}")
                if stored_room_id == room_id:
                    channel = room_name
            else:
                log.debug(f"room id: {room_id} active: {enabled}")

        if channel is None:
            log.debug(f"room id {room_id} found in room_list")
        else:
            log.debug(user_id)
            user_name = user_id.split(":")[0][1:]
            domain = user_id.split(":")[1]

            if user_name.startswith("_discord"):
                domain = "discord"
                user_name = user_name.lstrip("_discord_")

            elif user_name.startswith("freenode_"):
                domain = "frenode.org"
                user_name = user_name.lstrip("freenode_")

            await self.appservice.mark_read(room_id=room_id, event_id=event_id)

            self.bot.say_from(user_name, domain, channel, body)

    async def exit(self, signal_name):
        log.debug("Singal received exiting")
        # await self.clean_matrix_rooms()
        # loop.stop()
        sys.exit(0)

    def login(self, args=None):
        for channel in self.rooms:
            self.bot.channels_to_join.append(channel)
        self.bot.login(self.bot_username, self.bot_password)

    async def connect(self, server, port=8200, use_ssl=False, name=None, flags=None):
        """
        Connect to an SpringRTS Lobby server. Returns a proxy to an LobbyProtocol object.
        """
        protocol = None
        while protocol is None:
            try:
                transport, protocol = await self.loop.create_connection(LobbyProtocol, host=server, port=port, ssl=use_ssl)
            except ConnectionRefusedError as conn_error:
                log.info("HOST DOWN! retry in 10 secs {}".format(conn_error))
                await asyncio.sleep(10)

        log.info("connected")
        protocol.wrapper = LobbyProtocolWrapper(protocol)
        protocol.server_info = {"host": server, "port": port, "ssl": use_ssl}
        protocol.netid = "{}:{}:{}{}".format(id(protocol), server, port, "+" if use_ssl else "-")

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

        log.info("reconnecting")
        while protocol is None:
            await asyncio.sleep(10)
            try:
                transport, protocol = await self.loop.create_connection(LobbyProtocol, **server_info)
                client_wrapper.protocol = protocol

                asignal("netid-available").send(protocol)

                asignal("reconnected").send()

            except ConnectionRefusedError as conn_error:
                log.info("HOST DOWN! retry in 10 secs {}".format(conn_error))

