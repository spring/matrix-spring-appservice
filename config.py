# mautrix-telegram - A Matrix-Telegram puppeting bridge
# Copyright (C) 2019 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
from typing import Optional, Dict, List, Any

from mautrix.bridge.config import (BaseBridgeConfig, ConfigUpdateHelper)
from mautrix.util.config import BaseConfig, RecursiveDict
from ruamel.yaml.comments import CommentedMap

from ruamel.yaml import YAML


yaml = YAML()
yaml.indent(4)
yaml.width = 200


class Config(BaseBridgeConfig):
    def __getitem__(self, key: str) -> Any:
        try:
            return os.environ[f"MATRIX_JAURIA_{key.replace('.', '_').upper()}"]
        except KeyError:
            return super().__getitem__(key)

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        print(self)
        copy, copy_dict, base = helper

        copy("homeserver.address")
        copy("homeserver.domain")
        copy("homeserver.verify_ssl")

        if "appservice.protocol" in self and "appservice.address" not in self:
            protocol, hostname, port = (self["appservice.protocol"], self["appservice.hostname"],
                                        self["appservice.port"])
            base["appservice.address"] = f"{protocol}://{hostname}:{port}"
        else:
            copy("appservice.address")

        copy("appservice.hostname")
        copy("appservice.port")
        copy("appservice.max_body_size")

        copy("appservice.database")

        copy("appservice.id")

        copy("appservice.bot_username")
        copy("appservice.bot_displayname")
        copy("appservice.bot_avatar")

        copy("appservice.community_id")

        copy("appservice.as_token")
        copy("appservice.hs_token")

        copy("bridge.command_prefix")
        copy("bridge.username_template")
        copy("bridge.alias_template")
        copy("bridge.rooms")

    @property
    def namespaces(self) -> Dict[str, List[Dict[str, Any]]]:
        homeserver = self["homeserver.domain"]

        username_format = self["bridge.username_template"].format(userid=".+")
        alias_format = self["bridge.alias_template"].format(groupname=".+")
        group_id = ({"group_id": self["appservice.community_id"]}
                    if self["appservice.community_id"] else {})

        return {
            "users": [{
                "exclusive": True,
                "regex": f"@{username_format}:{homeserver}",
                **group_id,
            }],
            "aliases": [{
                "exclusive": True,
                "regex": f"#{alias_format}:{homeserver}",
            }]
        }