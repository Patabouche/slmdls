# SteaMidra - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# This file is part of SteaMidra.
#
# SteaMidra is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SteaMidra is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SteaMidra.  If not, see <https://www.gnu.org/licenses/>.

import logging
import shutil
from pathlib import Path
from typing import Optional

from colorama import Fore, Style

from sff.lua.choices import add_new_lua, download_lua, select_from_saved_luas
from sff.prompts import prompt_select
from sff.storage.named_ids import get_named_ids
from sff.structs import (
    LuaChoice,
    LuaChoiceReturnCode,
    LuaEndpoint,
    OSType,
    RawLua,
)
from sff.lua.parse_lua import GENERAL_ADDAPPID_REGEX, parse_lua_contents
from sff.utils import launcher_saved_lua_dir

logger = logging.getLogger(__name__)


class LuaManager:
    def __init__(
        self, os_type: OSType
    ):
        """Might need refactor. Does I/O on init"""
        self.saved_lua = launcher_saved_lua_dir()
        self.saved_lua.mkdir(parents=True, exist_ok=True)
        self.named_ids = get_named_ids(self.saved_lua)
        self.os_type = os_type
        self.last_endpoint: Optional[LuaEndpoint] = None

    def get_raw_lua(
        self, choice: LuaChoice, override: Optional[Path] = None
    ):
        while True:
            if choice == LuaChoice.SELECT_SAVED_LUA:
                result = select_from_saved_luas(self.saved_lua, self.named_ids)
            elif choice == LuaChoice.ADD_LUA:
                result = add_new_lua(override)
            elif choice == LuaChoice.AUTO_DOWNLOAD:
                result = download_lua(self.saved_lua, self.os_type)
                if result.endpoint is not None:
                    self.last_endpoint = result.endpoint
            switch = result.switch_choice
            if isinstance(switch, LuaChoice):
                choice = switch
            elif switch == LuaChoiceReturnCode.GO_BACK:
                return None
            if result.path is not None:
                lua_path = result.path
                if result.contents is not None:  # Usually a zip
                    lua_contents = result.contents
                else:
                    try:
                        lua_contents = result.path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        print(
                            Fore.RED + "This file is not a text file!" + Style.RESET_ALL
                        )
                        override = None
                        continue
                break
        return RawLua(lua_path, lua_contents)

    def fetch_lua(
        self,
        override_choice = None,
        override_path = None,
    ):
        while True:
            choice = (
                override_choice
                if override_choice
                else prompt_select("Choose:", list(LuaChoice), cancellable=True)
            )
            if choice is None:
                return None
            lua = self.get_raw_lua(choice, override_path)
            if lua is None:
                continue
            parsed = parse_lua_contents(lua.contents, lua.path)
            if parsed is None:
                if not GENERAL_ADDAPPID_REGEX.search(lua.contents):
                    print("App ID not found. Try again.")
                else:
                    print("Decryption keys not found. Try again.")
                continue
            print(f"App ID is {parsed.app_id}")
            return parsed

    def backup_lua(self, lua):
        target = self.saved_lua / f"{lua.app_id}.lua"
        if lua.path.suffix == ".zip":
            with target.open("w", encoding="utf-8") as f:
                f.write(lua.contents)
        else:
            try:
                shutil.copyfile(lua.path, target)
            except shutil.SameFileError:
                logger.debug("Skipped backup because it's the same file")
                pass
