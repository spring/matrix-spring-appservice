import asyncio
import logging.config
import sys
import copy
import yaml

from typing import Dict, List, Match, Optional, Set, Tuple, TYPE_CHECKING
from urllib.parse import quote

from matrix_client.api import MatrixHttpApi

from mautrix_appservice import AppService
from m_types import MatrixEvent, MatrixEventID, MatrixRoomID, MatrixUserID

from asyncspring import spring

with open("config.yaml", 'r') as yml_file:
    config = yaml.load(yml_file)

logging.config.dictConfig(copy.deepcopy(config["logging"]))
log = logging.getLogger("matrix-spring.init")  # type: logging.Logger
log.debug(f"Initializing matrix-spring")

loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop

state_store = "state_store.json"

mebibyte = 1024 ** 2

matrix_api = MatrixHttpApi(config["homeserver"]["address"])

appserv = AppService(config["homeserver"]["address"], config["homeserver"]["domain"],
                     config["appservice"]["as_token"], config["appservice"]["hs_token"],
                     config["appservice"]["bot_username"], log="spring_as", loop=loop,
                     verify_ssl=config["homeserver"]["verify_ssl"], state_store=state_store,
                     real_user_content_key="net.maunium.telegram.puppet",
                     aiohttp_params={"client_max_size": config["appservice"]["max_body_size"] * mebibyte
                                     })

DOMAINS = ["[matrix]", "[jauriarts]"]


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

    async def run(self):

        self.bot = await spring.connect(config["spring"]["address"],
                                        port=config["spring"]["port"],
                                        use_ssl=config["spring"]["ssl"],
                                        name="appservice")

        self.bot.channels_to_join.append("#test")
        self.bot.channels_to_join.append("#moddev")
        self.bot.channels_to_join.append("#sy")
        self.bot.channels_to_join.append("#s44")
        self.bot.channels_to_join.append("#springlobby")

        self.bot.login(config["spring"]["bot_username"],
                       config["spring"]["bot_password"])

    async def leave_all_matrix_rooms(self, username):
        user = appserv.intent.user(username)
        for room in await user.get_joined_rooms():
            await  user.leave_room(room)

    async def login_matrix_account(self, username):
        matrix_id = f"@spring_{username.lower()}:{config['homeserver']['domain']}"
        user = appserv.intent.user(matrix_id)

        task = [user.set_presence("online"),
                user.set_display_name(f"{username} (Lobby)")]

        loop.run_until_complete(asyncio.gather(*task, loop=loop))

    async def logout_matrix_account(self, username):
        matrix_id = f"@spring_{username.lower()}:{config['homeserver']['domain']}"
        user = appserv.intent.user(matrix_id)

        rooms = await user.get_joined_rooms()

        for room_id in rooms:
            await user.leave_room(room_id=room_id)

        task = [user.set_presence("offline")]

        loop.run_until_complete(asyncio.gather(*task, loop=loop))

    async def join_room(self, room, clients):
        room_alias = f"#spring_{room.lower()}:{config['homeserver']['domain']}"

        for client in clients:
            if client != "appservice":
                if not any(domain in client for domain in DOMAINS):
                    matrix_id = f"@spring_{client.lower()}:{config['homeserver']['domain']}"
                    user = appserv.intent.user(matrix_id)

                    await user.join_room(room_alias)

    async def leave_room(self, room, clients):
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

        await user.send_text(room_id, message)

    async def saidex(self, user, room, message):
        matrix_id = f"@spring_{user.lower()}:{config['homeserver']['domain']}"
        room_alias = f"#spring_{room}:{config['homeserver']['domain']}"

        if matrix_id == "@spring_glenda:jaurarts.org":
            return

        room_id = get_matrix_room_id(room_alias)
        user = appserv.intent.user(matrix_id)

        await user.send_emote(room_id, message)

    async def matrix_user_joined(self, matrix_username, room_id):
        if matrix_username.startswith("@spring_"):
            return

        print("matrix user Joined")
        print(room_id)

        display_name = await appserv.intent.get_displayname(user_id=matrix_username, room_id=room_id)

        room_alias = await get_matrix_room_alias(room_id)

        room_list = room_alias["aliases"]

        channel = None
        for room in room_list:
            if room.startswith("#spring_"):
                channel = room.split("_")[1].split(":")[0]

        domain = matrix_username.split(":")[1]
        username = matrix_username.split(":")[0][1:]

        self.bot.bridged_client_from(domain, username, display_name)
        self.bot.join_from(channel, domain, display_name)

    async def matrix_user_left(self, username, room):

        if username.startswith("@spring_"):
            return

        print(room)

        for room_alias in room['aliases']:
            room_id = get_matrix_room_id(room_alias)
            display_name = await appserv.intent.get_displayname(user_id=username, room_id=room_id)

            domain = username.split(":")[1].split(".")[0]
            spring_username = "[{1}]{0}".format(display_name, domain)

            self.bot.leave_from()

    async def say_from(self, matrix_username, room_id, body):

        if matrix_username.startswith("@spring_"):
            return

        room_alias = await get_matrix_room_alias(room_id)

        room_list = room_alias["aliases"]

        channel = None
        for room in room_list:
            if room.startswith("#spring_"):
                channel = room.split("_")[1].split(":")[0]

        if channel is None:
            log.info("no chanel found in alias")
        else:
            user = matrix_username.split(":")[0][1:]
            domain = matrix_username.split(":")[1]
            self.bot.say_from(user, domain, channel, body)


def main():
    with appserv.run(config["appservice"]["hostname"], config["appservice"]["port"]) as start:

        ################
        #
        # Initialization
        #
        ################

        log.info("Initialization complete, running startup actions")

        admin_list = config["appservice"]["admins"]
        admin_room = config["appservice"]["admin_room"]

        spring_appservice = SpringAppService()

        tasks = (spring_appservice.run(), start)
        loop.run_until_complete(asyncio.gather(*tasks, loop=loop))

        appservice_account = loop.run_until_complete(appserv.intent.whoami())
        user = appserv.intent.user(appservice_account)
        loop.run_until_complete(user.set_presence("online"))

        location = config["homeserver"]["domain"].split(".")[0]
        external_id = "MatrixAppService"
        external_username = config["appservice"]["bot_username"].split("_")[1]

        ################
        #
        # Matrix helper functions
        #
        ################

        async def handle_command(body):
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

        ################
        #
        # Matrix events
        #
        ################

        @appserv.matrix_event_handler
        async def handle_event(event: MatrixEvent) -> None:
            log.debug(event)

            event_type = event.get("type", "m.unknown")  # type: str
            room_id = event.get("room_id", None)  # type: Optional[MatrixRoomID]
            event_id = event.get("event_id", None)  # type: Optional[MatrixEventID]
            sender = event.get("sender", None)  # type: Optional[MatrixUserID]
            content = event.get("content", {})  # type: Dict

            if sender in admin_list:
                if room_id != admin_room:
                    return
                if event_type == "m.room.message":
                    body = content.get("body")
                    if body.startswith("!"):
                        await handle_command(body)
            else:
                if event_type == "m.room.message":
                    if sender.startswith("@spring"):
                        return
                    else:
                        body = content.get("body")
                        await spring_appservice.say_from(sender, room_id, body)

                elif event_type == "m.room.member":
                    membership = content.get("membership")
                    room_alias = await get_matrix_room_alias(room_id)

                    print(membership)

                    if membership == "join":
                        await spring_appservice.matrix_user_joined(sender, room_id)
                    elif membership == "leave":
                        await spring_appservice.matrix_user_left(sender, room_alias)


        ################
        #
        # Spring events
        #
        ################

        @spring_appservice.bot.on("clients")
        async def on_lobby_clients(message):
            if message.client.name == "appservice":
                channel = message.params[0]
                clients = message.params[1:]
                await spring_appservice.join_room(channel, clients)

        @spring_appservice.bot.on("joined")
        async def on_lobby_joined(message, user, channel):
            if message.client.name == "appservice":
                await spring_appservice.join_room(channel, [user.username])

        @spring_appservice.bot.on("left")
        async def on_lobby_left(message, user, channel, reason):
            if message.client.name == "appservice":
                await spring_appservice.leave_room(channel, [user.username])

        @spring_appservice.bot.on("said")
        async def on_lobby_said(message, user, target, text):
            if user == "Glenda":
                return
            if message.client.name == "appservice":
                await spring_appservice.said(user, target, text)

        @spring_appservice.bot.on("saidex")
        async def on_lobby_saidex(message, user, target, text):
            if user == "Glenda":
                return
            if message.client.name == "appservice":
                await spring_appservice.saidex(user, target, text)

        @spring_appservice.bot.on("denied")
        async def on_lobby_denied(message):
            if message.client.name != "appservice":
                user = message.client.name
                # await spring_appservice.register(user)

        @spring_appservice.bot.on("adduser")
        async def on_lobby_adduser(message):
            if message.client.name == "appservice":
                username = message.params[0]

                if username == "ChanServ":
                    return
                if username == "appservice":
                    return

                await spring_appservice.login_matrix_account(username)

        @spring_appservice.bot.on("removeuser")
        async def on_lobby_removeuser(message):
            if message.client.name == "appservice":
                username = message.params[0]

                if username == "ChanServ":
                    return
                if username == "appservice":
                    return

                await spring_appservice.logout_matrix_account(username)

        @spring_appservice.bot.on("accepted")
        async def on_lobby_accepted(message):
            pass

        log.info("Startup actions complete, now running forever")
        loop.run_forever()


if __name__ == "__main__":
    main()
