#!/usr/bin/env python3
# coding=utf-8
"""
CMake Build System Helper

A comprehensive build automation script for CMake projects using CMakePresets.json.
Provides a unified interface for configuring, building, testing, and packaging with
preset management, toolchain handling, and interactive menu selection.

Features:
  - Interactive curses-based preset selection menu
  - Support for CMakePresets.json and CMakeUserPresets.json
  - Automated toolchain configuration per platform
  - Build configuration, execution, testing, and packaging workflows
  - Package installation for development dependencies (Linux/Windows/Cygwin)
  - Colored logging with customizable verbosity
  - Environment variable management and macro expansion

Supported Platforms:
  - Linux (native, cross-compile for Windows/ARM)
  - Windows

Author: Arjan van Olphen <arjan@scanframe.nl>
"""

from __future__ import annotations
import argparse
import configparser
import logging
import stat
import platform
import re
import shutil
import sys
import time
import socket
import subprocess
import os
import json
import threading
import ctypes
import zipfile
import tempfile
import fnmatch
import io
from enum import Enum, auto
from string import Template
from typing import List, Any, Dict, Optional
from pathlib import Path
from abc import ABC, abstractmethod
from urllib.request import urlopen

# Auto-install for Windows the not standard 'curses' required module.
try:
	import curses
except ImportError as import_ex:
	if sys.platform == "win32":
		subprocess.check_call([sys.executable, "-m", "pip", "install", "windows-curses"])
		import curses
	else:
		raise import_ex

# Convenient type.
ParsedArguments = argparse.Namespace

# Template for 'build.ini' toolchain configuration file.
# noinspection SpellCheckingInspection
INI_TEMPLATE = r"""
; File for adding environment during the nested calls of the script.

[config]
; File for running an executable with the cmake environment.
cmake-run-file=cmake/lib/run-executable.cmake
; Override the default docker image using a smaller one without the QT libraries.
;docker-image=nexus.scanframe.com/amd64/gnu-cpp:24.04
;docker-image=avolphen/amd64-gnu-cpp:24.04

; Section for optional include file which is merged.
[__include__]
user=user.ini

[qt-ver]
RUN_QT_VER=6.10.1

; Environment added when running in Wine natively.
; It needs Python 3.12, CMake 4.2, Ninja 1.13 and NSIS 3.11 which can be installed but also shared through the toolchain directory.
; Windows Git is not completely working since it is using Cygwin libraries and a Git server/client is devised to overcome it.
[env.wine@]
; Convenient variable for common base directory.
TOOL_ROOT=Z:${RUN_DIR}\lib\toolchain\win-x86_64-cmake-4.2-combi
; Configuration for tools as cmake, git and ninja for within the Wine environment.
WINEPATH=${TOOL_ROOT}\cmake\bin;${TOOL_ROOT}\bin;${TOOL_ROOT}\python;${TOOL_ROOT}\nsis
; Alternate port for the git server incase of conflicts.
;GIT_SERVER_PORT=8888
; Alternate Wine prefix directory.
;WINEPREFIX=

; Environment added before running Docker.
[env.docker@]
; Nothing yet.

; Environment added before running with the compiler msvc natively.
[env.msvc@]
; Location of the root of the MSVC toolchain in the Wine environment.
; The rest is environment as below is configured in the file CMakePresets.json to allow multiple compilers to be configured in the same project.
MSVC_ROOT=${RUN_DIR}\lib\toolchain\w64-x86_64-msvc-2022
;MSVC_ROOT=P:\toolchain\w64-x86_64-msvc-2022
PATH=${RUN_DIR}\lib\qt\w64-x86_64\6.10.1\msvc_64\bin;${PATH}
; Puts the binary in 'bin/win64-msvc'.
SF_EXEC_DIR_SUFFIX=-msvc

; Environment added before running with the compiler msvc in Wine.
[env.msvc.wine@]
__inherit__=qt-ver
; Location of the root of the MSVC toolchain in the Wine environment.
; The rest is environment as below is configured in the file CMakePresets.json to allow multiple compilers to be configured in the same project.
MSVC_ROOT=${RUN_DIR}\lib\toolchain\w64-x86_64-msvc-2022
; Overrides QT_VER_DIR in the for subcommand 'run'.
RUN_QT_VER_DIR=${RUN_DIR}\lib\qt\w64-x86_64\${RUN_QT_VER}
SF_EXEC_DIR_SUFFIX=-msvc

; Environment added before running Wine in the Docker container.
[env.wine.docker@]
__inherit__=qt-ver
; Overrides QT_VER_DIR in the for subcommand 'run'.
RUN_QT_VER_DIR=Z:\home\${USER}\lib\qt\w64-x86_64\${RUN_QT_VER}

; Environment added before running with the compiler msvc in Wine in the Docker container.
[env.msvc.wine.docker@]
# The Docker container is build with the MSVC toolchain. (fuse-zip mounted in the home directory).
MSVC_ROOT=Z:\home\${USER}\toolchain\w64-x86_64-msvc-2022
SF_EXEC_DIR_SUFFIX=-msvc

; Environment added before running the 'gnu' compiler natively.
[env.gnu@]
__inherit__=qt-ver
SF_EXEC_DIR_SUFFIX=-gnu
# Normally the RUN_PATH is dealing with this but when compiled differently it must be set.
LD_LIBRARY_PATH=${RUN_DIR}/lib/qt/lnx-x86_64/${RUN_QT_VER}/gcc_64/lib

; Environment added when running wine natively to execute the Windows cross-compiled targets.
[env.gw@]
__inherit__=qt-ver
SF_EXEC_DIR_SUFFIX=-gw
WINEPATH=Z:\usr\x86_64-w64-mingw32\lib;Z:\usr\lib\gcc\x86_64-w64-mingw32\13-posix
; Overrides QT_VER_DIR in the for subcommand 'run'.
RUN_QT_VER_DIR=${RUN_DIR}/lib/qt/win-x86_64/${RUN_QT_VER}

; Environment added before running the 'mingw' compiler natively.
[env.mingw@]
__inherit__=qt-ver
SF_EXEC_DIR_SUFFIX=-mingw
; Only the path is required. Notice that some of the distributed MinGW compiler include older versions of Ninja and CMake.
PATH=${RUN_DIR}\lib\toolchain\w64-x86_64-mingw-1320-posix\bin;${RUN_DIR}\lib\qt\w64-x86_64\${RUN_QT_VER}\mingw_64\bin;lib;${PATH}

[env.mingw.wine@]
__inherit__=env.mingw@

; Environment added before running the 'mingw' compiler in Docker and Wine.
[env.mingw.wine.docker@]
__inherit__=qt-ver
SF_EXEC_DIR_SUFFIX=-mingw
PATH=Z:\home\${USER}\toolchain\w64-x86_64-mingw-1320-posix\bin;Z:\home\${USER}\lib\qt\w64-x86_64\${RUN_QT_VER}\mingw_64\bin;lib;${PATH}

; Environment added before running the 'ga' compiler in Docker.
[env.ga.docker@]
; Puts the binary in 'bin/lnx64-ga'.
SF_EXEC_DIR_SUFFIX=-ga

; Environment added before running the 'gw' compiler in the Docker container.
[env.gw.docker@]
__inherit__=qt-ver
SF_EXEC_DIR_SUFFIX=-gw
; Provides compiler std libraries to be found.
WINEPATH=Z:\usr\x86_64-w64-mingw32\lib;Z:\usr\lib\gcc\x86_64-w64-mingw32\13-posix
# Optional for allowing the .exe files to be executed from Linux. Required compiler std libraries are also part of the Qt library.
;WINEPATH=Z:\home\${USER}\lib\qt\win-x86_64\${RUN_QT_VER}\mingw_64\bin;lib
; Overrides QT_VER_DIR since Wine does not pass any 'QT_' prefixed variables.
RUN_QT_VER_DIR=/home/${USER}/lib/qt/win-x86_64/${RUN_QT_VER}

; Environment added before running the 'gnu' compiler in the Docker container.
[env.gnu.docker@]
__inherit__=qt-ver
SF_EXEC_DIR_SUFFIX=-gnu
# Normally the RUN_PATH is dealing with this but when compiled differently it must be set.
;LD_LIBRARY_PATH=/home/${USER}/lib/qt/lnx-x86_64/${RUN_QT_VER}/gcc_64/lib

""".replace('\r', '')


def is_wine() -> bool:
	"""
	Tells if this script is run from within Linux Wine.
	:return: True when in Wine, False otherwise.
	"""

	def _is_wine() -> bool:
		try:
			# Load ntdll and check for the Wine-specific version function
			if hasattr(ctypes, "windll"):
				ntdll = ctypes.windll.ntdll
				return hasattr(ntdll, "wine_get_version")
		except (AttributeError, OSError):
			pass
		return False

	if not hasattr(is_wine, "flag"):
		is_wine.flag = _is_wine()
	return is_wine.__getattribute__("flag")


def is_docker() -> bool:
	"""
	return Get the flag when running in docker.
	:return: True when Docker is active, False otherwise.
	"""

	def _is_docker() -> bool:
		# When running in Wine, check a different filepath.
		# noinspection SpellCheckingInspection
		fn = f"{os.sep}.dockerenv" if not is_wine() else f"Z:{os.sep}.dockerenv"
		return os.path.isfile(fn)

	if not hasattr(is_docker, "flag"):
		is_docker.flag = _is_docker()
	return is_docker.__getattribute__("flag")


def get_7z_exe() -> str:
	"""
	Finds the installation path of 7-Zip on a Windows system by querying the system's registry.
	:return: The full path to the `7z.exe` executable.
	:raise: FileNotFoundError when not found.
	"""
	if sys.platform != "win32":
		# noinspection PyDeprecation
		if path := shutil.which("7z"):
			return path
		ex = FileNotFoundError(f"Missing 7z file in path !")
		ex.add_note("Check if the package is installed.")
		raise ex

	try:
		import winreg
		# Open the 7-Zip registry key
		key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip")
		# Get the value of the "Path" entry
		path, _ = winreg.QueryValueEx(key, "Path")
		winreg.CloseKey(key)
		# Construct a full path to 7z.exe
		full_path = os.path.join(path, "7z.exe")
		if not os.path.exists(full_path):
			raise FileNotFoundError(f"Missing file at location '{full_path}' !")
		return full_path
	except Exception as ex:
		ex.add_note("Check if 7z executable is installed. Maybe required WinGet packages are not installed.")
		raise ex


def get_container_id() -> str:
	"""Returns the ID of the running container if it exists."""
	try:
		result = subprocess.run(["docker", "ps", "--filter", f"name={CONTAINER_NAME}", "--quiet"], capture_output=True,
			text=True, check=True)
		return result.stdout.strip()
	except subprocess.CalledProcessError:
		return ""


def start_git_server(port: int) -> bool:
	"""
	Starts the listener in a background thread.
	:param port: Port to listen on.
	:return: True on success.
	"""

	def translate_path(wine_path: str):
		"""
		Converts a path from Wine to the host.
		:param wine_path:
		:return:
		"""
		# Standardize separators
		wine_path = wine_path.replace('\\', '/')
		# Extract drive letter (e.g., 'C:')
		if len(wine_path) < 2 or wine_path[1] != ':':
			return wine_path  # Already a relative or Unix-style path
		drive_letter = wine_path[0:2].lower()  # 'c:'
		path_suffix = wine_path[2:].lstrip('/')
		# Locate the 'dosdevices' directory.
		wine_prefix = RUN_ENV.get('WINEPREFIX', os.path.expanduser('~/.wine'))
		dos_devices_path = os.path.join(wine_prefix, 'dosdevices')
		# The symlink for a drive is exactly the drive letter (e.g., ~/.wine/dosdevices/c:)
		drive_link = os.path.join(dos_devices_path, drive_letter)
		if os.path.islink(drive_link):
			# Resolve the symlink to the actual Linux path
			target_root = os.path.realpath(drive_link)
			return os.path.join(target_root, path_suffix)
		# Fallback if the link doesn't exist (unlikely for active drives)
		return wine_path

	def server_loop():
		"""
		Thread function.
		:return: None
		"""
		server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		server.bind(('127.0.0.1', port))
		server.listen(10)
		logger.info(f"= Git Proxy Listener started on port '{port}'.")
		while True:
			conn, addr = server.accept()
			try:
				raw_data = conn.recv(4096).decode('utf-8')
				if not raw_data:
					continue
				payload = json.loads(raw_data)
				# Assemble the command.
				cmd = ['git'] + payload['args']
				# Execute Git and capture everything
				logger.info(f"= Git server: {' '.join(cmd)}")
				proc = subprocess.run(cmd, cwd=translate_path(payload['cwd']), capture_output=True,
					# Captures both stdout and stderr
					text=False  # Keep as bytes for raw data transfer
				)
				# Prepare the response using hex encoding prevents JSON breakages.
				# noinspection PyUnresolvedReferences
				response = {"exit_code": proc.returncode, "stdout": proc.stdout.hex(), "stderr": proc.stderr.hex()}
				conn.sendall(json.dumps(response).encode('utf-8'))
			finally:
				conn.close()

	# Launch the main server loop in its own thread
	threading.Thread(target=server_loop, daemon=True).start()
	return True


class DebugMode(Enum):
	"""
	Defines the logging and reporting of commands being executed.
	"""
	REPORT = auto()
	"""Reports the executed command and executes it as well."""
	REPORT_ONLY = auto()
	"""Reports the executed command only, so no execution takes place."""
	SILENT = auto()
	"""Does not report in any case."""


# Flag determining the terminal is dumb or needs to be dumb is the case of a CI pipeline.
TERM_DUMB: bool = (not sys.stderr.isatty() or os.environ.get("CI") or os.environ.get("TERM") in ["dumb", "unknown"])


# Enumeration of types.
class PresetTypes(Enum):
	"""
	Enumerate of CMake preset types.
	"""
	CONFIGURE = "configure"
	BUILD = "build"
	TEST = "test"
	PACKAGE = "package"
	WORKFLOW = "workflow"


class ColoredFormatter(logging.Formatter):
	"""
	A logging formatter that applies color coding based on message content and log level.

	This class allows customization of log messages by applying ANSI color codes to the messages.
	The color applied depends on the prefix of the
	log message and the logging level of the record.
	"""

	class ColorCodes(Enum):
		"""
		Defines the colors for logging.
		"""
		BLACK = "\033[30m" if not TERM_DUMB else ""
		RED = "\033[31m" if not TERM_DUMB else ""
		GREEN = "\033[32m" if not TERM_DUMB else ""
		YELLOW = "\033[1;33m" if not TERM_DUMB else ""
		BLUE = "\033[1;34m" if not TERM_DUMB else ""
		MAGENTA = "\033[35m" if not TERM_DUMB else ""
		CYAN = "\033[36m" if not TERM_DUMB else ""
		WHITE = "\033[1;37m" if not TERM_DUMB else ""
		RESET = "\033[0m" if not TERM_DUMB else ""

	def format(self, record: logging.LogRecord):
		"""
		Formats a log message with optional color-coded prefixes based on the content.
		"""
		# Strip white space before checking.
		msg = record.getMessage().strip()
		color = self.ColorCodes.RESET
		if msg.startswith("-"):
			color = self.ColorCodes.CYAN
		elif msg.startswith("~"):
			color = self.ColorCodes.BLUE
		elif msg.startswith("#"):
			color = self.ColorCodes.YELLOW
		elif msg.startswith("="):
			color = self.ColorCodes.GREEN
		elif msg.startswith(":"):
			color = self.ColorCodes.MAGENTA
		elif msg.startswith("!"):
			color = self.ColorCodes.RED
		elif record.levelno >= logging.ERROR:
			color = self.ColorCodes.RED
		color_code = color
		return f"{color_code.value}{record.getMessage().expandtabs(2)}{self.ColorCodes.RESET.value}"


# Setup logging.
logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(ColoredFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
# To calculate the time elapsed.
start_time = time.time()


def create_config_parser(ini_path: str, cfg: configparser.ConfigParser = None) -> configparser.ConfigParser:
	"""Creates the config parser."""
	create_flag = True if cfg is None else False
	if not cfg:
		logger.info(f"# Configuration file: {ini_path}")
		cfg = configparser.ConfigParser()
	cfg.optionxform = str
	# Create the file if it does not exist yet.
	if create_flag and not os.path.exists(ini_path) and not is_wine() and not is_docker():
		logger.info(f"# Creating non-existing configuration file: {ini_path}")
		with open(ini_path, "w", encoding="utf-8") as file:
			file.write(INI_TEMPLATE)
	cfg.read(ini_path)
	if cfg.has_section(section := "__include__"):
		items = cfg.items(section)
		cfg.remove_section(section)
		for key, file in items:
			logger.info(f"# Configuration include file: {file}")
			create_config_parser(ini_path=str(os.path.join(RUN_DIR, file)), cfg=cfg)
	return cfg


# Show the Python used.
logger.info(f"# Python {sys.version} on {sys.platform}.")
# The directory of the current file.
RUN_DIR = os.path.dirname(os.path.abspath(__file__))
# Environment variables from this process.
PARENT_ENV = os.environ.copy()
# Linux has a current working directory environment variable and Windows does not.
if 'PWD' not in PARENT_ENV:
	PARENT_ENV['PWD'] = os.getcwd()
# List of optional environment variable names when missing no exception is raised.
ENV_OPTIONAL = ["SF_BIN_DIR_SUFFIX", "WINEPATH", "LD_LIBRARY_PATH"]
# List of ignored environment variables set when a CI pipeline is active.
ENV_IGNORED = ["SF_EXEC_DIR_SUFFIX"] if PARENT_ENV.get("CI") else []
# In Linux and Docker it could be the TEMP environment variable is not set.
if 'TEMP' not in PARENT_ENV:
	PARENT_ENV['TEMP'] = tempfile.gettempdir()
# Add the RUN_DIR so it is available in the '.toolchain-*' files.
PARENT_ENV['RUN_DIR'] = RUN_DIR
# Environment variables for running a command with.
RUN_ENV = PARENT_ENV.copy()
# Global debug flag for system commands.
DEBUG_FLAG = False
# Holds the current configuration preset name.
CONFIG_PRESET = None
# Default container name for detached operations.
CONTAINER_NAME = "cpp_builder"
# Default SSH port for ssh daemon.
SSHD_PORT = 8022
# Name of the project subdirectory.
PROJECT_SUBDIR = os.path.basename(RUN_DIR)
# Get the configuration of the script.
CONFIG = create_config_parser(os.path.join(RUN_DIR, str(os.path.splitext(os.path.basename(__file__))[0] + ".ini")))
# Default Qt version for the Docker image selection.
QT_VER = "6.10.1"
# Directory to store the CMake library files.
CMAKE_LIB_SUBDIR = ["cmake", "lib"]


def get_github_release(owner: str, repo: str, assets_wildcard: Optional[str] = None, release_tag: Optional[str] = None) -> Optional[Dict[str, any]]:
	"""
	Fetch GitHub release information and assets.
	:param owner: Repository owner
	:param repo: Repository name
	:param assets_wildcard: Filter assets by wildcard.
	:param release_tag: Specific release version (e.g., "1.2.3"). If None, fetches the latest release.
	:return: Dictionary with 'release', 'assets', and 'url' fields, or None if not found.
		- release: Release version string
		- assets: List of asset download info (name, url, size)
		- url: Base URL for the release
	"""
	import requests
	try:
		if release_tag is None:
			# Fetch the latest release.
			api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
		else:
			# Fetch the specific release by tag
			api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{release_tag}"
		resp = requests.get(api_url, headers={"Accept": "application/vnd.github.v3+json"}, timeout=15)
		if resp.status_code == 404:
			return None
		resp.raise_for_status()
		data = resp.json()
		# Extract release info
		release_tag = data.get("tag_name", "").lstrip('v')
		assets_list = []
		for asset in data.get("assets", []):
			asset_name = asset.get("name", "")
			if assets_wildcard and not fnmatch.fnmatch(asset_name, assets_wildcard):
				continue
			assets_list.append({
				"name": asset_name,
				"url": asset.get("browser_download_url", ""),
				"size": asset.get("size", 0),
				"digest": asset.get("digest", None)
			})
		return {
			"release": release_tag,
			"assets": assets_list,
			"url": data.get("html_url", "")
		}
	except requests.RequestException:
		return None


def extract_by_url(url: str, dest_dir: str, new_dir_name: Optional[str] = None, digest:Optional[str] = None) -> bool:
	"""
	Extracts the url of a given compressed file to the given destination directory.
	After extraction the directory is renamed to new_dir_name.
	"""
	import tarfile
	import requests
	import hashlib

	try:
		# Create the destination directory if it doesn't exist.
		dest_path = Path(dest_dir)
		dest_path.mkdir(parents=True, exist_ok=True)
		# Download the file
		resp = requests.get(url, timeout=60, stream=True)
		resp.raise_for_status()
		# Determine file extension from URL
		filename = url.split('/')[-1]
		# Download to the temporary file.
		sha256_hash = hashlib.sha256() if digest else None
		with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp_file:
			for chunk in resp.iter_content(chunk_size=1024*4):
				tmp_file.write(chunk)
				if sha256_hash:
					sha256_hash.update(chunk)
			tmp_path = tmp_file.name
		# Verify digest if provided.
		if digest:
			computed_digest = sha256_hash.hexdigest()
			expected_digest = digest.split(':', 1)[1] if ':' in digest else digest
			if computed_digest != expected_digest:
				Path(tmp_path).unlink(missing_ok=True)
				logger.error(f"! Digest mismatch (expected/got):  {expected_digest} / {computed_digest}")
				return False
			else:
				logger.info(f"= Digest matches: {computed_digest}")
		else:
			logger.warning(f": No digest for this download: {filename}")
		try:
			# Extract based on the file type.
			if filename.endswith(('.tar.gz', '.tgz')):
				with tarfile.open(tmp_path, 'r:gz') as tar:
					tar.extractall(dest_path)
					# Get the root directory name from the archive
					members = tar.getmembers()
					if members:
						root_dir = members[0].name.split('/')[0]
					else:
						return False
			elif filename.endswith('.tar.bz2'):
				with tarfile.open(tmp_path, 'r:bz2') as tar:
					tar.extractall(dest_path)
					members = tar.getmembers()
					if members:
						root_dir = members[0].name.split('/')[0]
					else:
						return False
			elif filename.endswith('.zip'):
				with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
					zip_ref.extractall(dest_path)
					# Get the root directory name from the archive.
					names = zip_ref.namelist()
					if names:
						root_dir = names[0].split('/')[0]
					else:
						return False
			else:
				return False
			# Rename the extracted directory if new_dir_name is provided
			if new_dir_name and root_dir != new_dir_name:
				old_path = dest_path / root_dir
				new_path = dest_path / new_dir_name
				if old_path.exists():
					# Remove destination if it exists
					if new_path.exists():
						shutil.rmtree(new_path)
					old_path.rename(new_path)
			# Signal success.
			return True
		finally:
			# Clean up temporary file
			Path(tmp_path).unlink(missing_ok=True)

	except Exception as e:
		logger.error(f"Error extracting {url}: {e}")
		return False

def get_config_section(section: str, fail: bool = True) -> Dict[str, str]:
	"""
	Gets a configuration section as Dict of key-value pairs.
	"""
	if not CONFIG.has_section(section):
		logger.error(f"! Configuration section '{section}' does not exist.")
		if fail:
			raise RuntimeError(f"Missing configuration section '{section}' !")
		return {}
	return dict(CONFIG.items(section))


def get_merged_config_section(section: str, fail: bool = True) -> Dict[str, str]:
	"""
	Gets an assembled dictionary of key-value pairs using inheritance.
	"""
	if not CONFIG.has_section(section):
		logger.error(f"! Configuration section '{section}' does not exist.")
		if fail:
			raise RuntimeError(f"Missing configuration section '{section}' !")
	# Final merged result (Child values override parents)
	merged_data: Dict[str, str] = {}
	# Track visited sections to detect redundancy and prevent infinite loops
	visited = set()
	# Process queue (Breadth-First traversal of inheritance)
	queue = [section]
	while queue:
		current_section = queue.pop(0)
		# Report if a section is encountered more than once in the tree
		if current_section in visited:
			logger.warning(f": Notice: Section [{current_section}] was inherited more than once.")
			continue
		visited.add(current_section)
		# parser.items() provides the keys/values for the section
		current_items = dict(CONFIG.items(current_section) if current_section else {})
		# Extract inheritance instructions
		if inheritance_val := current_items.pop("__inherit__", None):
			# noinspection PyUnresolvedReferences
			parents = [p.strip() for p in inheritance_val.split(",")]
			for parent in parents:
				if parent and not CONFIG.has_section(parent):
					logger.warning(f"Warning: Parent section [{parent}] (inherited by [{current_section}]) does not exist.")
				else:
					queue.append(parent)
		# Merge values: only add if the key doesn't already exist.
		for key, value in current_items.items():
			if key not in merged_data:
				merged_data[key] = value
	return merged_data


def remove_tree(dir_name: Path) -> None:
	"""
	Remove the complete passed directory tree, even when some files are read-only.
	Needed to remove Git read-only files or directories.
	:param dir_name: Directory name as a Path object or string.
	:return: None
	"""

	# noinspection PyUnusedLocal
	def remove_readonly(func, path, exc_info):
		"""
		Change the file mode before deleting to allow deletion.
		"""
		# Check if the file is writable before changing it.
		if os.path.exists(path) and not os.access(path, os.W_OK):
			# Clear the read-only bit.
			os.chmod(path, stat.S_IWRITE)
			# Retry the deletion.
			func(path)

	shutil.rmtree(dir_name, onerror=remove_readonly)


def menu_selection(options: dict[Any, str], title: str | None = "Make a Selection", caption: str = "Select an option?"
) -> Any | None:
	"""
	Curses menu styled after the Linux 'dialog' utility.
	Returns: Associated key (Any) or 'None' if canceled.
	"""
	# Convert dictionary values to a list for positional rendering and keys to a list for retrieval by index.
	option_keys = list(options.keys())
	option_values = list(options.values())
	# Key conversion for when using in Wine.
	wine_conversion = {450: curses.KEY_UP, 456: curses.KEY_DOWN, 452: curses.KEY_LEFT,
		454: curses.KEY_RIGHT, } if is_wine() else {}

	def _get_key(win):
		"""
		Determines and returns a meaningful key representation or raw key code based on
		input from the provided window object.

		:param win: A window object that provides the `getch` method to capture input.
		:type win: Any
		:return: Returns a string representing directional keys ("UP", "DOWN", "LEFT",
		         "RIGHT") if the input matches predefined key codes. Otherwise,
		         returns the raw key code.
		:rtype: Union[str, int]
		"""
		key = win.getch()
		if key in wine_conversion:
			key = wine_conversion[key]
		return key

	def _menu(std_scr):
		# Initialize Colors
		curses.start_color()

		# Some terminals require this to enable bright colors with A_BOLD
		# noinspection PyBroadException
		try:
			curses.use_default_colors()
		except Exception:
			pass

		# Pair 1: Cyan on a blue background for the screen.
		curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLUE)
		# Pair 2: Black text on a gray background for a dialog box.
		curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
		# Pair 3: Bright White text on a blue background for selection.
		curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)
		# Pair 4: Shadow (Black on Black).
		curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_BLACK)
		#
		curses.curs_set(0)
		std_scr.keypad(True)
		# -Startup Resize Trigger.
		curses.ungetch(curses.KEY_RESIZE)
		current_row = 0
		# Track the first visible item in the list.
		top_offset = 0

		while True:
			# Always get current screen dimensions at the start of the loop
			sh, sw = std_scr.getmaxyx()
			# Setup Background
			std_scr.bkgd(' ', curses.color_pair(1))
			std_scr.erase()
			# Main Screen Title - Trimmed if needed
			safe_title = title[:max(1, sw - 4)]
			if sw > 2:
				std_scr.addstr(0, 1, f"{safe_title}", curses.A_BOLD | curses.color_pair(1))
				std_scr.addstr(1, 1, "\u2500" * (sw - 2), curses.A_BOLD | curses.color_pair(1))
			# Calculate Dimensions dynamically based on current sh, sw
			max_box_height = max(1, sh - 6)
			needed_height = len(option_values) + 4
			height = min(needed_height, max_box_height)
			# Calculate width based on caption and the longest display string
			width = max(len(opt) for opt in [caption] + option_values) + 10
			width = min(width, sw - 4)
			# Ensure minimum window size to prevent newwin errors
			height = max(3, height)
			width = max(10, width)
			start_y = max(0, (sh - height) // 2)
			start_x = max(0, (sw - width) // 2)
			# Calculate how many items can be displayed.
			visible_count = max(0, height - 4)
			# Adjust the scrolling of the window.
			if current_row < top_offset:
				top_offset = current_row
			elif current_row >= top_offset + visible_count:
				top_offset = max(0, current_row - visible_count + 1)
			# Draw Shadow
			if start_y + height < sh and start_x + width < sw:
				# noinspection PyBroadException
				try:
					shadow = curses.newwin(height, width, start_y + 1, start_x + 1)
					shadow.bkgd(' ', curses.color_pair(4))
					std_scr.noutrefresh()
					shadow.noutrefresh()
				except Exception:
					std_scr.noutrefresh()
			else:
				std_scr.noutrefresh()
			# Setup Dialog Window
			# noinspection PyBroadException
			try:
				menu_win = curses.newwin(height, width, start_y, start_x)
				menu_win.bkgd(' ', curses.color_pair(2))
				menu_win.box()
				menu_win.keypad(True)
				# Draw the Caption ON TOP of the border
				if width > 4:
					trimmed_caption = caption[:width - 4]
					menu_win.addstr(0, 2, f" {trimmed_caption} ", curses.color_pair(2))
				# Draw the options with scrolling logic
				for i in range(visible_count):
					idx = i + top_offset
					if idx >= len(option_values):
						break
					row_text = option_values[idx]
					y, x = i + 2, 4
					item_width = width - 8
					if item_width > 0:
						display_text = row_text[:item_width].ljust(item_width)
						if idx == current_row:
							menu_win.attron(curses.color_pair(3) | curses.A_BOLD)
							menu_win.addstr(y, x, display_text)
							menu_win.attroff(curses.color_pair(3) | curses.A_BOLD)
						else:
							menu_win.addstr(y, x, display_text, curses.color_pair(2))
				menu_win.refresh()
			except Exception:
				std_scr.refresh()
				menu_win = std_scr
			# Input Handling
			key = _get_key(menu_win)
			if key == curses.KEY_UP and current_row > 0:
				current_row -= 1
			elif key == curses.KEY_DOWN and current_row < len(option_values) - 1:
				current_row += 1
			elif key in [curses.KEY_ENTER, 10, 13]:
				# Return the key associated with the selected value
				return option_keys[current_row]
			# Keys to quit on.
			elif key in [27, ord('q'), ord('Q')]:
				return None
			elif key == curses.KEY_RESIZE:
				try:
					curses.update_lines_cols()
				except AttributeError:
					pass
				std_scr.clear()

	rv = curses.wrapper(_menu)
	# Write something to asure that lines are written after existing text in the console.
	logger.info(f"# Menu selection: {rv}")
	return rv


def ask_selection(options: dict[Any, str], title: str | None = "Make a Selection", caption: str = "Select an option?"
) -> Any | None:
	"""
	Displays a numeric selection menu from a dictionary and returns the corresponding key.
	- options: Dict where value is displayed and key is returned.
	- 'q': returns None.
	- Invalid input: prompts again.
	"""
	# Copy the arguments to pass on to the menu function.
	func_args = locals().copy()
	# Check if the 'fancy' attribute flag is set.
	fancy_menu = ask_selection.__getattribute__("fancy") if hasattr(ask_selection, "fancy") else True
	# When a dumb terminal is detected, use the curses menu.
	if not TERM_DUMB and fancy_menu:
		return menu_selection(**func_args)
	# Continue as a normal console menu.
	print(title)
	# When all keys are boolean act differently.
	if all(isinstance(k, bool) for k in options):
		while True:
			reply = input(f"{caption} (y/n/q): ").strip().lower()
			if reply == 'y':
				return True
			if reply == 'n':
				return False
			if reply == 'q':
				break
	else:
		# Create a stable list of keys to map numbers to the original dict keys.
		keys_list = list(options.keys())
		while True:
			print("[0] Quit")
			for i, key in enumerate(keys_list, start=1):
				print(f"[{i}] {options[key]}")
			reply = input(f"\n{caption} ").strip().lower()
			if reply == 'q' or reply == '0':
				break
			if reply.isdigit():
				selection_idx = int(reply) - 1
				if 0 <= selection_idx < len(keys_list):
					return keys_list[selection_idx]
				else:
					print(f"Error: Please enter a number between 1 and {len(options)}.")
			else:
				print("Error: Invalid input. Enter a number or 'q' to quit.")
	return None


class CallbackEnvironment(dict):
	"""
	Callback for getting environment variables and when missing raises an Exception.
	"""

	def __init__(self, environment: Dict[str, str], context: Dict[str, str] = None, note_str: str | None = None):
		super().__init__()
		self.note = note_str
		self.context = context
		self.environment = environment

	def __getitem__(self, key):
		value = None
		if key in self.environment:
			value = self.environment.get(key, None)
		elif self.context is not None and key in self.context:
			value = self.context[key]
		# Check if still not found.
		if value is None:
			if key in ENV_OPTIONAL:
				logger.debug(f": Missing environment variable '{key}' returning empty string instead.")
				return ""
			exception = RuntimeError(f"Missing environment variable '{key}' !")
			exception.add_note(self.note)
			raise exception
		return value


def set_environment(compiler_type: str | None = None) -> None:
	"""Sets the run environment according to the configuration in the ini-file."""

	# Key name used for inheritance.
	inherit_key = "__inherit__"

	def fix_wine_path(wine_path: str) -> str:
		"""
		Fixes the given Wine path by resolving nested symlinks into a usable path.
		This is useful when sharing toolchain directories between projects using symlinks.
		"""
		result: List[str] = []
		for d in wine_path.split(";"):
			if d.startswith("Z:"):
				d = os.path.realpath(d[2:].replace("\\", "/"))
				result += ["Z:" + d.replace("/", "\\")]
			else:
				if d.startswith("/"):
					d = "Z:" + d.replace("/", "\\")
				result += [d]
		return ";".join(result)

	def get_config_inheritance(_section: str) -> List[str]:
		"""
		Gets the inheritance of the passed section.
		"""
		visited = []
		queue = [_section]
		while queue:
			sec = queue.pop(0)
			# Report if a section is encountered more than once in the tree
			if sec in visited:
				logger.warning(f"Notice: Section [{sec}] was inherited more than once.")
				continue
			visited.append(sec)
			# Add the inherited sections to the queue.
			secs = [p.strip() for p in CONFIG.get(sec, inherit_key, fallback="").split(",") if p.strip()]
			secs.reverse()
			queue += secs
		visited.reverse()
		return visited

	# Reset the RUN_ENV dictionary to the parent environment.
	global RUN_ENV
	# Start with a fresh copy of the parent environment.
	RUN_ENV = PARENT_ENV.copy()
	# Assemble the name of the section.
	parts = ["env"]
	parts += [compiler_type if compiler_type is not None else sys.platform]
	if is_wine():
		parts += ["wine"]
	if is_docker():
		parts += ["docker"]
	section = '.'.join(parts) + '@'
	system_section = section + platform.node()
	# Check if the system-named entry exists in the configuration.
	if CONFIG.has_section(system_section):
		logger.info(f"# Using environment configuration '{system_section}'.")
		section = system_section
	else:
		logger.info(f"# Using environment configuration '{section}' instead of '{system_section}'.")
	for cur_section in get_config_inheritance(section):
		for key, value in get_config_section(cur_section).items():
			if key == inherit_key:
				continue
			if key not in ENV_IGNORED:
				RUN_ENV[key] = Template(value).safe_substitute(
					CallbackEnvironment(environment=RUN_ENV, note_str=f"Configuration section: {section}"))
				# Fix the path since it must be with Windows backslashes only.
				if key == "WINEPATH":
					RUN_ENV[key] = fix_wine_path(RUN_ENV.get(key, ""))
				logger.info(f"~ Environment Set: {key}={RUN_ENV[key]}")
			else:
				logger.info(f"~ Environment Ignored: {key}")


def get_compiler_type(preset_name: str, preset_type: PresetTypes = PresetTypes.CONFIGURE) -> str | None:
	"""
	Gets the compiler type from the field 'vendor/compiler' of the 'configure' preset.
	Alternatively, the 'cacheVariables/SF_COMPILER/value' field is tried.
	:param preset_name: Name of preset.
	:param preset_type: Type of preset defaulting to CONFIGURE.
	:return: None when not found and a string otherwise.
	"""
	if (cpn := get_configure_preset_name(preset_type, preset_name)) is not None:
		if (pn := get_preset_by_name(PresetTypes.CONFIGURE, cpn)) is not None:
			compiler_type = pn.get("vendor", {}).get("compiler", None)
			# Try the cache variable.
			if compiler_type is not None:
				logger.debug(f"# Compiler type from field 'vendor/compiler': {compiler_type}")
			else:
				compiler_type = pn.get("cacheVariables", {}).get("SF_COMPILER", {}).get("value", None)
				if compiler_type is not None:
					logger.debug(f"# Compiler type from field 'cacheVariables/SF_COMPILER': {compiler_type}")
			# Modify the environment.
			return compiler_type
	else:
		logger.warning(f"! No {PresetTypes.CONFIGURE.value} preset found for '{preset_type.value}/{preset_name}'!")
	return None


def set_environment_by_preset(preset_name: str, preset_type: PresetTypes = PresetTypes.CONFIGURE) -> bool:
	"""
	Sets the toolchain environment using the preset field 'vendor/compiler' of the 'configure' preset.
	Alternatively, the 'cacheVariables/SF_COMPILER/value' field is tried.
	:param preset_name: Name of preset.
	:param preset_type: Type of preset defaulting to CONFIGURE.
	:return: True if the toolchain environment was set, False otherwise.
	"""
	compiler_type = get_compiler_type(preset_name, preset_type)
	if compiler_type is not None:
		# Modify the environment.
		set_environment(compiler_type)
		return True
	return False

def expand_macros(preset: dict, value: Any, is_path: bool = False, context: Dict[str, str] = None) -> Any:
	"""
	Recursively expands macros, substituting environment variables in strings from CMakePresets.json.
	"""
	if value is None:
		return None
	if isinstance(value, dict):
		return {k: expand_macros(preset, value=v) for k, v in value.items()}
	if isinstance(value, list):
		return [expand_macros(preset, v) for v in value]
	if not isinstance(value, str):
		return value
	preset_name = preset.get("name", "unknown")
	value = value.replace("${presetName}", preset_name)
	value = value.replace("${sourceDir}", RUN_DIR)
	value = value.replace("${sourceParentDir}", os.path.dirname(RUN_DIR))
	value = value.replace("${fileDir}", RUN_DIR)
	value = value.replace("${pathListSep}", os.pathsep)
	value = value.replace("${hostSystemName}", "Windows" if sys.platform == 'win32' else "Linux")
	value = value.replace("${dollar}", "$")

	def env_replacer(match):
		"""Callback function for regular expression substitution."""
		env_src = match.group(1)
		var_name = match.group(2)
		return CallbackEnvironment(environment=RUN_ENV, context=context if env_src == "env" else {},
			note_str=f"Replacing in preset '{preset_name}' variable '${env_src}{{{var_name}}}'.")[var_name]

	pat = r'\$(env|penv)\{([^}]+)\}'
	while re.search(pat, value):
		value = re.sub(pat, env_replacer, value)
	if is_path and sys.platform == 'win32':
		value = value.replace('/', os.sep)
	return value


def run_command(cmd_list: List[str], input_data: bytes = None, shell: bool = False, capture_output: bool = False, check: bool = True,
	cwd: str = None, dbg_mode: DebugMode = DebugMode.REPORT
) -> subprocess.CompletedProcess | None:
	"""
	Utility to run shell commands.
	Raises 'subprocess.CalledProcessError' if the command fails.
	"""
	cwd = os.getcwd() if cwd is None else cwd
	# When debugging, and the command is to report only.
	if DEBUG_FLAG and dbg_mode == DebugMode.REPORT_ONLY:
		cmd_str = " ".join(cmd_list)
		logger.info(f"~ Not executing from ({cwd}): {cmd_str}")
		# Simulate a completion.
		return subprocess.CompletedProcess(args=cmd_list, returncode=0)
	# Report when not mode is not silent.
	if dbg_mode != DebugMode.SILENT or DEBUG_FLAG:
		cmd_str = " ".join(cmd_list)
		logger.info(f"~ Executing from({cwd}): {cmd_str}")
	# Raises a 'CalledProcessError' exception on error.
	try:
		return subprocess.run(cmd_list, shell=shell, cwd=cwd, check=check, env=RUN_ENV, capture_output=capture_output, input=input_data)
	except Exception as ex:
		ex.add_note(f"Subprocess: {' '.join(cmd_list)}")
		raise ex


def get_merged_presets() -> dict:
	"""
	Get the merged presets from CMakePresets.json and CMakeUserPresets.json.
	:return: A dictionary containing the merged presets.
	"""
	# Use a cached version of the merged presets if available.
	if hasattr(get_merged_presets, "merged_data"):
		return get_merged_presets.merged_data
	else:
		get_merged_presets.merged_data = {}
	# Make 'merged' reference the attribute.
	merged = get_merged_presets.merged_data

	def deep_merge(source, destination):
		"""
		Recursively merges the contents of the source dictionary into the destination dictionary.
		If a key exists in both dictionaries and its value is also a dictionary, this function
		will recursively merge those nested dictionaries. For non-dictionary values, the value
		from the source dictionary will overwrite or add to the destination.
		"""
		for key, value in source.items():
			if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
				# Recursively merge nested dictionaries.
				deep_merge(value, destination[key])
			else:
				# Overwrite or add the value.
				if key not in destination:
					destination[key] = value
		return destination

	base_path = os.path.join(RUN_DIR, "CMakePresets.json")
	user_path = os.path.join(RUN_DIR, "CMakeUserPresets.json")
	# Array Fields: Concatenate preset arrays (configure, build, test, etc.)
	preset_type_fields = [f"{item.value}Presets" for item in list(PresetTypes)]
	# Load files (handle missing UserPresets gracefully)
	with open(base_path, 'r') as f:
		merged.update(json.load(f))
	if os.path.exists(user_path):
		with open(user_path, 'r') as f:
			data = json.load(f)
		# Versioning: UserPresets version typically takes precedence for the union.
		merged['version'] = max(merged.get('version', 1), data.get('version', 1))
		if int(merged['version']) < 6:
			raise RuntimeError(f"{base_path} file is required to be version 6 or higher!")
		for field in preset_type_fields:
			if field in data:
				# Initialize the field in merged if it doesn't exist.
				if field not in merged:
					merged[field] = []
				# Overwrite Rule: If a user preset has the same name as a base preset, the user preset overrides it.
				user_presets_dict = {p['name']: p for p in data[field]}
				# Remove existing presets in a base that usernames override.
				merged[field] = [p for p in merged[field] if p['name'] not in user_presets_dict]
				# Append all user presets (including the overrides)
				merged[field].extend(data[field])
		# Vendor Maps: Shallow merge vendor-specific data
		if "vendor" in data:
			merged.setdefault("vendor", {}).update(data["vendor"])
	# Merge all in inherited presets.
	for field in preset_type_fields:
		# Assemble a dictionary of presets by name first.
		presets: dict[str, dict] = {}
		for preset in merged[field]:
			presets.setdefault(preset['name'], preset)
		# Merge inherited presets.
		for preset in merged[field]:
			inherits = preset.get("inherits", None)
			if inherits:
				cur_preset_name = preset['name']
				# Iterate through the inherited presets and merge them in.
				for preset_name in inherits:
					deep_merge(presets[preset_name], preset)
				# Sanity check after merge.
				if cur_preset_name != preset['name']:
					logger.debug(f"! Failed to merge properly.")
	# Return the cached value.
	return get_merged_presets.merged_data


def get_valid_presets(preset_type: PresetTypes) -> list[str]:
	"""
	Gets a list of valid presets of a specified type from the command output.
	:param preset_type: The type of preset to query.
	:return: A list of strings representing the names of the valid presets.
	"""
	# Use a cached version of the merged presets if available.
	if hasattr(get_valid_presets, "result"):
		return get_valid_presets.result

	lines = run_command(["cmake", "--list-presets", preset_type.value], capture_output=True,
		dbg_mode=DebugMode.SILENT).stdout.decode("utf-8")
	get_valid_presets.result = re.findall(r'^\s+\"([a-zA-Z_\-]+)\"\s+-', lines, re.MULTILINE)
	return get_valid_presets.result


def select_preset(preset_type: PresetTypes | str | None = None) -> str | None:
	"""
	Selects a preset or displays information on all available presets from CMakePresets.json.
	:param preset_type:
	"""
	# When showing information and a dialog is eminent, check if this is a dumb terminal.
	if TERM_DUMB and preset_type is not None:
		raise RuntimeError("Cannot select preset using a dialog when the terminal is dumb!")
	if preset_type is None:
		logger.info("# Information on all presets.")
	elif type(preset_type) is str:
		logger.info(f"# Information on presets named: {preset_type}")
	# Only used when a preset_type was passed.
	options: dict[str, str] = {}
	# Get valid configure presets to dismiss other presets by.
	valid_configure_presets = get_valid_presets(preset_type=PresetTypes.CONFIGURE)
	# Retrieve the preset data from CMakePresets.json
	data = get_merged_presets()
	for pt in list(PresetTypes) if type(preset_type) is not PresetTypes else [preset_type]:
		key = f"{pt.value}Presets"
		# Retrieve the by CMake considered valid presets.
		valid_presets = get_valid_presets(preset_type=pt)
		presets = data.get(key, [])
		# Filter out hidden presets.
		visible_presets = []
		for p in presets:
			if p.get("name") in valid_presets:
				# Special check for workflow presets. The 'configure' preset [0] must be valid.
				if pt == PresetTypes.WORKFLOW:
					if len(steps := p.get("steps", [])):
						# The first step is always the 'configure' step, add the workflow entry when it is valid.
						if steps[0].get("type") == PresetTypes.CONFIGURE.value and steps[0].get("name") in valid_configure_presets:
							visible_presets += [p]
				else:
					visible_presets += [p]
		if visible_presets:
			for p in visible_presets:
				name = p.get("name", "")
				if type(preset_type) is str and preset_type != name:
					logger.debug(f"# Skipping {pt.value} preset: {name}")
					continue
				display_name = p.get("displayName", "")
				description = p.get("description", "")
				info_line = name
				if display_name:
					info_line += f" ({display_name})"
				if description:
					info_line += f": {description}"
				if type(preset_type) is PresetTypes:
					options[name] = info_line
					continue
				else:
					logger.info(f"\t- {pt.value.title()}: {info_line}")
				# When showing 'test' presets also show the tests if available.
				if key == "configurePresets":
					cvs = p.get("cacheVariables", {})
					for cvn in cvs:
						cve = cvs.get(cvn, {})
						logger.info(f"\t\t~ {cvn}:{cve.get("type", "")}={cve.get("value", "")}")
				# When showing 'test' presets also show the tests if available.
				if key == "testPresets":
					lines = run_command(["ctest", "--preset", name, "--show-only"], capture_output=True,
						dbg_mode=DebugMode.SILENT).stdout.decode("utf-8")
					lines = re.findall(r'^\s+(Test #.*)$', lines, re.MULTILINE)
					if len(lines):
						for line in lines:
							logger.info(f"\t\t~ {line}")
					else:
						logger.info(f"\t\t: Need cmake configuration step for this information.")
				# When showing 'workflow' presets also show the steps.
				if key == "workflowPresets":
					steps = p.get("steps", [])
					if steps:
						index = 0
						for s in steps:
							index += 1
							logger.info(f"\t\t~ Step #{index}: {s.get("type", "")}({s.get("name", "")})")

	# When no preset type is passed, just log the found entries.
	if type(preset_type) is not PresetTypes:
		return None
	# Return the selected preset string.
	return ask_selection(options, title=f"{preset_type.value.title()} Selection", caption="Select a preset:")


def select_target(preset_type: PresetTypes, preset_name: str) -> str | None:
	"""
	Selects a target for a specific preset type and name.
	:param preset_type: Preset type
	:param preset_name: Name of the preset.
	:return: The target name when selected, 'None' when not.
	"""
	if preset_type == PresetTypes.BUILD:
		lines = run_command(["cmake", "--build", "--preset", preset_name, "--target", "help"], capture_output=True,
			dbg_mode=DebugMode.SILENT).stdout.decode("utf-8")
		options: dict[str, str] = {}
		for trg in re.findall(r'^([^/\s]+):', lines, re.MULTILINE):
			# Remove noise by skipping targets with slashes or _autogen in the name.
			if "/" in trg or "_autogen" in trg:
				continue
			options[trg] = trg
		return ask_selection(options, title=f"{preset_type.value.title()} Selection", caption="Select a target:")

	if preset_type == PresetTypes.TEST:
		cmd = ["ctest", "--preset", preset_name, "--show-only=json-v1"]
		data = json.loads(run_command(cmd, capture_output=True, dbg_mode=DebugMode.SILENT).stdout.decode("utf-8"))
		if type(data) is dict:
			tests = data.get("tests", [])
			options: dict[str, str] = {}
			for test in tests:
				name = test.get("name", "")
				label_props = [v for v in test.get("properties", []) if v['name'] == 'LABELS']
				labels = "" if not len(label_props) else ", ".join(label_props[0]['value'])
				options[name] = f"{name} ({labels})"
			# Return the selected preset string.
			return ask_selection(options, title=f"{preset_type.value.title()} Selection", caption="Select a target:")

	return None


def get_preset_by_name(preset_type: PresetTypes, preset_name: str) -> dict | None:
	"""
	Gets a typed preset dictionary by name.
	:param preset_type: Type of the preset, e.g. 'configure', 'build', 'test', 'package', 'workflow'.
	:param preset_name:  Name of the preset defined in CMakePresets.json or CMakeUserPresets.json.
	:return: The preset dictionary or None when not found.
	"""
	data = get_merged_presets()
	for p in data.get(f"{preset_type.value}Presets", []):
		if p.get("name") == preset_name:
			return p
	return None


def get_configure_preset_name(preset_type: PresetTypes, preset_name: str) -> str | None:
	"""
	Gets the 'configure' preset name from a given other type of preset.
	:param preset_type: Type of the preset, e.g. 'configure', 'build', 'test', 'package', 'workflow'.
	:param preset_name:  Name of the preset defined in CMakePresets.json or CMakeUserPresets.json.
	:return: The preset dictionary or None when not found.
	"""
	# Nothing special here.
	if preset_type == PresetTypes.CONFIGURE:
		return preset_name
	if preset_type in [PresetTypes.BUILD, PresetTypes.TEST, PresetTypes.PACKAGE]:
		p = get_preset_by_name(preset_type, preset_name)
		if p is not None:
			return p.get("configurePreset", None)
	if preset_type == PresetTypes.WORKFLOW:
		p = get_preset_by_name(preset_type, preset_name)
		if p is not None:
			steps = p.get("steps", None)
			# Sanity check on the first step.
			if len(steps) and all(k in steps[0] for k in ["name", "type"]) and steps[0]["type"] == PresetTypes.CONFIGURE:
				return steps[0]["name"]
	return None


class HelpAction(argparse._HelpAction):
	"""Action handler for printing the help the intended way, which is otherwise not possible."""

	class HelpException(Exception):
		"""Exception class as a hack to avoid parser.exit() being called and print help the intended way."""

		def __init__(self):
			super().__init__("Help requested.")

	def __call__(self, parser, namespace, values, option_string=None):
		parser.print_help()
		raise HelpAction.HelpException


class SubCommand(ABC):
	"""Subcommand handler class."""

	# Static member to registry all subcommands.
	registry: Dict[str, SubCommand] = {}
	# Get the script's name.
	script = os.path.basename(__file__)

	def __init__(self, command: str, aliases: list[str] = None):
		"""Initializes the SubCommand with a specific parser instance."""
		# Command name.
		self.command: str = command
		# Command aliases.
		self.aliases: List[str] = aliases if aliases is not None else []
		# Holds the sub-parser instance for this subcommand.
		self.parser: argparse.ArgumentParser | None = None

	def register(self) -> SubCommand:
		"""Registers this class in to the static member of this same class."""
		# Automatically register the instance upon creation.
		SubCommand.registry[self.command] = self
		return self

	@abstractmethod
	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		"""Create a sub parser for the command."""
		self.parser = subparsers.add_parser(name=self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter, help=f"Run with command '{self.command}'.", description="")
		return self.parser

	@abstractmethod
	def options(self, parser: argparse.ArgumentParser):
		"""Add options to the sub parser."""
		parser.add_argument("-h", "--help", action=HelpAction, default=False, help="Shows the command's help.")
		# Configure the command line options.
		parser.add_argument("-d", "--dry-run", action="store_true", help="Show executed commands without executing them.")

	def parse_args(self, args: List[str], show_help: bool = True) -> argparse.Namespace | None:
		"""
		Parses the command line arguments for testing.
		:param args: Argument list.
		:param show_help: Show help on failure to parse.
		:return: None on failure and parsed arguments on success.
		"""
		parser = self.options(argparse.ArgumentParser(add_help=False, formatter_class=argparse.RawTextHelpFormatter))
		parser.help = None
		parser.epilog = None
		# noinspection PyBroadException
		try:
			if show_help:
				return parser.parse_args(args, show_help=True)
			else:
				return parser.parse_known_args(args)[0]
		except Exception:
			if show_help:
				parser.print_help()
			return None

	@abstractmethod
	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str] | None) -> int:
		"""Virtual function to be implemented by subclasses."""
		# Check if debugging is enabled.
		global DEBUG_FLAG
		if args.dry_run:
			# Set the global debug flag.
			DEBUG_FLAG = True
			# Report also debugging.
			logger.setLevel(logging.DEBUG)
			logger.debug("# Logger set to level DEBUG.")
		return 0

	def print_help(self):
		"""Prints the command help when the parser exists."""
		if self.parser:
			self.parser.print_help()
		pass


class SubCommandNative(SubCommand):
	"""Subcommand handler for native execution."""

	def __init__(self):
		super().__init__("native", ["n", "_"])

	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		self.parser = subparsers.add_parser(self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Run native on this Linux or Windows host.")
		self.parser.epilog = f"""
	Examples:
	
	 List files in the configure preset's binary directory:
		 Linux: 
			 ./{self.script} {self.command} -p gnu-debug
		 Windows:
			 {self.script} {self.command} -p mingw-debug
			 
	 Run executable in with the working directory as the binary: 
		 Linux: 
			 ./{self.script} {self.command} -p gnu-debug
			 SF_EXEC_DIR_SUFFIX=-gnu ./{self.script} {self.command} -p gnu-debug -- ./hello-world.bin
		 Windows:
			 SF_EXEC_DIR_SUFFIX=-msvc {self.script} {self.command} -p msvc-debug -- hello-world.exe
"""
		return self.parser

	def options(self, parser: argparse.ArgumentParser):
		"""Adds standard options to the given parser. """
		# Adds the standard help option.
		super().options(parser)
		parser.add_argument("-i", "--info", action="store_true", help="Return information on presets.")
		parser.add_argument("-c", "--clean", action="store_true",
			help="Remove the built artifacts first (cmake option '--clean-first').")
		parser.add_argument("-f", "--fresh", action="store_true",
			help="Configure a fresh build tree (cmake option --fresh).")
		parser.add_argument("-C", "--wipe", action="store_true", help="Wipe build directory contents.")
		parser.add_argument("-l", "--list-only", action="store_true", help="Lists tests only.")
		parser.add_argument("-m", "--make", action="store_true", help="Create build directory/makefiles only.")
		parser.add_argument("-b", "--build", action="store_true",
			help="Build target(s) and make config when it does not exist.")
		parser.add_argument("-B", "--build-only", action="store_true",
			help="Build target(s) only and fail when the configuration does not exist.")
		parser.add_argument("-t", "--test", action="store_true", help="Runs ctest using a test-preset.")
		parser.add_argument("-T", "--test-select", action="store_true", help="Runs ctest using a dialog selecting a test.")
		parser.add_argument("-R", "--test-regex", type=str, metavar="<regex>",
			help="Regular expression on which test names are to be executed.")
		parser.add_argument("-p", "--package", action="store_true", help="Create packages.")
		parser.add_argument("-w", "--workflow", action="store_true", help="Runs workflow presets.")
		parser.add_argument("-n", "--target", type=str, metavar="<trg>",
			help="Overrides the build targets set in the preset by a single target.")
		parser.add_argument("-N", "--target-select", action="store_true",
			help="Selects a single target single target to build.")
		parser.add_argument("--no-fancy", action="store_true", help="Disables the fancy menu/dialog for selections.")
		parser.add_argument("preset", nargs="?",
			help="Single preset to process and when omitted a dialog is shown to select one.")
		# Create additional help text.
		parser.epilog = f"""
  Examples:
    Get all project presets info:
      {self.script} --info 
    Get single project presets by name:
      {self.script} --info gnu-debug
    Make/Build a preset:
      {self.script} -mb gnu-debug
      {self.script} --make -build gnu-debug
    Run all tests on a preset:
      {self.script} --test gnu-debug
    Run specific tests using a regex:
      {self.script} -t gnu-debug -r '^t_my-test'
    Workflow (Make/Build/Test/Pack) a preset:
      {self.script} --workflow gnu-debug
"""
		return parser

	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str] | None) -> int:
		"""
		Handles the default/standard execution of the script.
		:return: Exit code.
		"""
		# Call parent to handle the common dry-run option.
		super().handle(args, args_left, args_right)
		# Set the menu to appear not fancy since in Wine it demolishes the terminal.
		ask_selection.fancy = not args.no_fancy and not is_wine()

		if args.info:
			# Passing None will show all available presets.
			select_preset(args.preset)
			return 0

		# The 'configure' preset name also functioning as a flag as well.
		config_preset_name: str | None = None
		# The 'build' preset name also functioning as a flag as well.
		build_preset_name: str | None = None
		# Flag to indicate that the build step triggers the make/configure step.
		make_by_build: bool = False
		# Binary directory.
		bin_dir: str = ""

		if args.build or args.build_only:
			# Check if a preset was passed and if not, select one.
			build_preset_name = args.preset if args.preset else select_preset(PresetTypes.BUILD)
			if build_preset_name is None:
				return 1
			# Get the referenced 'configure' preset name from the 'build' preset.
			if (config_preset_name := get_configure_preset_name(PresetTypes.BUILD, build_preset_name)) is None:
				logger.error(f"! Build preset '{build_preset_name}' does not reference a configure preset.")
				return 1
			logger.info(f"# Using configure preset '{config_preset_name}' from build preset '{build_preset_name}'.")
			# Set the flag triggering a make by the build step.
			make_by_build = True

		# When configure step is to be made.
		if args.make or make_by_build:
			# Check if a preset was passed and if not, select one.
			if config_preset_name is None:
				config_preset_name = args.preset if args.preset else select_preset(PresetTypes.CONFIGURE)
			if config_preset_name is None:
				return 1
			# Set the environment variables according to the preset's 'configure' preset.
			set_environment_by_preset(config_preset_name, PresetTypes.CONFIGURE)
			# Check if the preset was found.
			config_preset = get_preset_by_name(PresetTypes.CONFIGURE, config_preset_name)
			# When the preset was not found, exit.
			if config_preset is None:
				logger.error(f"! Configure preset with name '{config_preset_name}' not found.")
				return 1
			# Get the binary directory from preset expanding then macros.
			bin_dir = expand_macros(config_preset, config_preset.get("binaryDir", None), True)
			if bin_dir is None:
				logger.error(f"! Field 'binaryDir' not found for configure preset '{config_preset_name}'.")
				return 1
			else:
				logger.info(f"# Binary Directory: {bin_dir}")
			# Get the full path to the binary directory if not already absolute.
			bin_dir = os.path.abspath(bin_dir)
			# When build only, do not configure.
			if not args.build_only:
				# Check if the directory should be wiped.
				if args.wipe and bin_dir:
					if os.path.exists(bin_dir):
						logger.info(f"# Wiping directory: {bin_dir}")
						if not args.dry_run:
							remove_tree(Path(bin_dir))
				# When the build triggered a make and the binary directory exists, make is not needed.
				if args.make or (make_by_build and not os.path.exists(os.path.join(bin_dir, "CMakeCache.txt"))):
					# os.makedirs(bin_dir, exist_ok=True)
					# Logic for configuration
					cmd = ["cmake", "-Wno-dev", "--preset", config_preset_name]
					# cmd.append("--trace")
					# Add the command option to delete the CMakeCache.txt file.
					if args.fresh:
						cmd.append("--fresh")
					# Execute the configure command for creating makefiles.
					run_command(cmd, dbg_mode=DebugMode.REPORT_ONLY)

		if args.build or args.build_only:
			# Check if a preset was passed and if not, select one.
			if not os.path.exists(os.path.join(bin_dir, "CMakeCache.txt")):
				logger.error(f"! Missing build directory: {bin_dir}")
				return 1
			cmd = ["cmake", "--build", "--preset", build_preset_name]
			cmd += ["--parallel", str(os.cpu_count())]
			if args.clean:
				cmd.append("--clean-first")
			if args.target_select:
				args.target = select_target(PresetTypes.BUILD, build_preset_name)
			if args.target:
				cmd.extend(["--target", args.target])
				logger.debug(f"# Select build target: {args.target}")
			if not args.target_select or args.target_select and not args.target is None:
				run_command(cmd, dbg_mode=DebugMode.REPORT_ONLY)

		if args.test or args.list_only or args.test_select or args.test_regex:
			preset_name = args.preset if args.preset else select_preset(PresetTypes.TEST)
			if preset_name is None:
				return 0
			# Set the environment variables according to the preset's 'configure' preset.
			set_environment_by_preset(preset_name, PresetTypes.TEST)
			if args.test_select and not args.list_only:
				target = select_target(PresetTypes.TEST, preset_name)
				if target is None:
					return 0
				run_command(["ctest", "--preset", preset_name, '--tests-regex', f"^{target}$"],
					dbg_mode=DebugMode.REPORT_ONLY)
			else:
				cmd = ["ctest", "--preset", preset_name]
				if args.list_only:
					cmd.append("--show-only")
				if args.test_regex:
					cmd.extend(["--tests-regex", args.test_regex])
				cmd.append("--verbose")
				run_command(cmd, dbg_mode=DebugMode.REPORT_ONLY)

		if args.package:
			preset_name = args.preset if args.preset else select_preset(PresetTypes.PACKAGE)
			if preset_name is None:
				return 0
			# Set the environment variables according to the 'configure' preset.
			set_environment_by_preset(preset_name, PresetTypes.PACKAGE)
			cmd = ["cpack", "--preset", preset_name, "--verbose"]
			run_command(cmd, dbg_mode=DebugMode.REPORT_ONLY)

		if args.workflow:
			preset_name = args.preset if args.preset else select_preset(PresetTypes.WORKFLOW)
			if preset_name is None:
				return 0
			# Set the environment variables according to the 'configure' preset.
			set_environment_by_preset(preset_name, PresetTypes.PACKAGE)
			cmd = ["cmake", "--workflow", "--preset", preset_name]
			run_command(cmd, dbg_mode=DebugMode.REPORT_ONLY)

		logger.info("# Build script completed successfully.")
		return 0


class SubCommandWine(SubCommand):
	"""Subcommand handler for the '_' command."""

	def __init__(self):
		super().__init__("wine", ["w"])

	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		self.parser = subparsers.add_parser(self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Run in Wine on Linux. (uses a Git client/server solution)")
		return self.parser

	def options(self, parser: argparse.ArgumentParser):
		"""Adds options to the given parser for the wine command."""
		# Adds the standard help option.
		super().options(parser)
		parser.add_argument("-g", "--git-server", action="store_true", help="Force start of git-server in the background.")
		# Define Epilog for the help message.
		parser.epilog = f"""Examples:
  Compile using Microsoft Visual C++ on Linux
    ./{self.script} {self.command} -- -b msvc-debug
"""

	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str] | None) -> int:
		"""
		Handles the 'wine' command execution of the script.
		:return: Exit code.
		"""
		# Call parent to handle the common dry-run option.
		super().handle(args, args_left, args_right)
		# noinspection PyDeprecation
		if shutil.which("wine") is None:
			logger.error(f"! The 'wine' command not found. Please install required packages.")
			return 1

		# When the temporary directory by environment variable 'TEMP' is used, the cmake build directory is not preserved.
		# To make the 'TEMP' a valid location with Wine in Docker, it needs to be in the project which is mounted on the host.
		if is_docker() and "HOME" in RUN_ENV:
			user_dir = os.path.join(RUN_ENV["HOME"], ".wine/drive_c/users/user")
			temp_dir = os.path.join(user_dir, "Temp")
			if not os.path.exists(temp_dir) and os.path.exists(user_dir):
				os.symlink(os.path.join(os.path.abspath(os.path.curdir), "cmake-build"), os.path.join(user_dir, "Temp"))
		# Set the run environment for wine since start_git_server() uses it.
		set_environment("wine")
		if args_right:
			if not args_right[0] in ["run"]:
				# Split the arguments again on the second '--' and parse the right command arguments and show help when invalid.
				cmd_args = SubCommandNative().parse_args(split_arguments(args_right)[0], False)
				if cmd_args:
					args.git_server = cmd_args.make or cmd_args.build or cmd_args.workflow
				# Start running the git server only when needed or forced.
				if args.git_server:
					if not start_git_server(int(RUN_ENV.get('GIT_SERVER_PORT', '9999'))):
						return 1
			# Suppress Wine fix-me messages when 'WINEDEBUG' is not set.
			if "WINEDEBUG" not in RUN_ENV:
				RUN_ENV["WINEDEBUG"] = 'fixme-all'
			arguments = ["wine", "python", self.script] + args_right
			logger.debug(f"# Running: WINEPATH='{RUN_ENV.get("WINEPATH", "")}' {' '.join(arguments)}")
			return run_command(arguments, dbg_mode=DebugMode.REPORT_ONLY).returncode
		return 0


class SubCommandDocker(SubCommand):
	"""Subcommand handler for the 'docker' command."""

	def __init__(self):
		super().__init__("docker", ["d"])

	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		self.parser = subparsers.add_parser(self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Run in a docker environment(Linux only).")
		return self.parser

	def options(self, parser: argparse.ArgumentParser):
		"""Adds options to the given parser for the docker command."""
		# Adds the standard help option.
		super().options(parser)
		# Platform detection logic based on machine architecture.
		machine = platform.machine()
		default_platform = "arm64" if machine == 'aarch64' else "amd64"
		cfg = get_config_section("config", fail=True)
		# Define Epilog for the help message.
		parser.epilog = f"""Examples:
  Show the targets using the {default_platform} platform docker image and Qt version {QT_VER}:
    {self.script} --platform {default_platform} --qt-ver '{QT_VER}' -- --info
  Show the uname information of the arm64 container without QT libraries:
    {self.script} --platform arm64 --qt-ver '' run -- uname -a
	"""
		parser.add_argument("command", type=str, nargs="?",
			choices=["pull", "run", "start", "wstart", "stop", "kill", "prune", "attach", "status", "sshd", "versions"],
			help=f"""
pull         - Pulls the docker image from the Docker registry.
run -- <cmd> - Runs a command as user 'user' in the container using Docker command.
start        - Starts a container named '{CONTAINER_NAME}' in the background.
wstart       - Starts a container named '{CONTAINER_NAME}' in the background and a wineserver for speed.
attach       - Attaches to the running container named '{CONTAINER_NAME}'.
status       - Returns info of the running container '{CONTAINER_NAME}'.
prune        - Remove unused data and anonymous volumes.
stop/kill    - Stops/Kills the container named '{CONTAINER_NAME}'.
versions     - Shows versions of most installed applications within the container.
sshd         - Starts sshd service on port {SSHD_PORT} to allow remote control.
""")
		# Check if a fixed docker image is set.
		if "docker-image" in cfg.keys():
			parser.description = f"""
Docker image from configuration: {cfg["docker-image"]}
This ignores the options: --qt-ver, --platform'
"""
		parser.add_argument("-q", "--qt-ver", default=QT_VER, metavar="<qt-ver>",
			help=f"Qt version forming the Docker image name (default: '{QT_VER}').")
		parser.add_argument("-p", "--platform", default=default_platform, choices=['amd64', 'arm64'],
			help=f"Platform part forming the Docker image (default: '{default_platform}').")
		parser.add_argument("-n", "--no-build-dir", action="store_false", dest="flag_build_dir", default=True,
			help="Docker project builds in a regular cmake-build directory as a native build would.")

	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str] | None) -> int:
		"""
		Handles the 'docker' command execution of the script.
		:return: Exit code.
		"""
		# Call parent to handle the common dry-run option.
		super().handle(args, args_left, args_right)

		def docker_command(options: List[str], image: str, cmd_args: List[str]) -> List[str]:
			"""Determines whether to use 'docker exec' on a running container or 'docker run' for a new one."""
			if get_container_id():
				# If the container is already running (detached), use exec.
				full_cmd = ["docker", "exec", "--interactive", "--tty", CONTAINER_NAME, "sudo", "--login", "--user=user", "--"]
				full_cmd += cmd_args
			else:
				# Otherwise start a fresh container.
				full_cmd = ["docker", "run"] + options + [image] + cmd_args
			return full_cmd

		# Construct the Docker image name.
		img_name = f"nexus.scanframe.com/{args.platform}/gnu-cpp:24.04-{args.qt_ver}".rstrip('-')
		# Check if the image name is overridden.
		img_name = get_config_section("config", fail=True).get("docker-image", img_name)
		logger.info(f"# Docker image used: {img_name}")
		# Prepare standard Docker options for running the container.
		docker_opts = ["--platform", f"linux/{args.platform}", "--rm", "--tty", "--interactive", "--device", "/dev/fuse",
			"--cap-add", "SYS_ADMIN", "--security-opt", "apparmor:unconfined", "--hostname", platform.node(), "--user", "0:0",
			"--env", f"LOCAL_USER={os.getuid()}:{os.getgid()}", "--network", "host"]
		# Handle X11 Display forwarding if available on the host.
		# noinspection SpellCheckingInspection
		if os.environ.get("DISPLAY"):
			xauth = os.environ.get("XAUTHORITY")
			if not xauth:
				xauth = Path.home() / ".Xauthority"
			# noinspection SpellCheckingInspection
			docker_opts += ["--env", "DISPLAY", "--volume", f"{xauth}:/home/user/.Xauthority:ro"]
		# Map the project root directory.
		docker_opts += ["--volume", f"{RUN_DIR}:/mnt/project/{PROJECT_SUBDIR}:rw"]
		# Configure a specific build directory volume if requested.
		if args.flag_build_dir:
			build_dir = Path(RUN_DIR) / "cmake-build" / f"docker-{args.platform}-{args.qt_ver}".strip("-")
			build_dir.mkdir(parents=True, exist_ok=True)
			docker_opts += ["--volume", f"{build_dir}:/mnt/project/{PROJECT_SUBDIR}/cmake-build:rw"]
		# Set the working directory within the container.
		docker_opts += ["--workdir", f"/mnt/project/{PROJECT_SUBDIR}/"]
		# Determine the specific command and its arguments.
		command = args.command
		# Set the environment before calling a docker command.
		set_environment("docker")
		# Command Execution logic based on the provided command.
		if command == "pull":
			run_command(["docker", "pull", img_name], dbg_mode=DebugMode.REPORT_ONLY)
		elif command == "status":
			if not get_container_id():
				logger.warning(f": Container '{CONTAINER_NAME}' is not running.")
				return 1
			if (exit_code := run_command(["docker", "ps", "--filter", f"name={CONTAINER_NAME}"],
				dbg_mode=DebugMode.REPORT_ONLY).returncode) != 0:
				return exit_code
			return run_command(docker_command(docker_opts, img_name, ["ps", "ax"]),
				dbg_mode=DebugMode.REPORT_ONLY).returncode
		#
		elif command in ["stop", "kill"]:
			cntr_id = get_container_id()
			if cntr_id:
				logger.info(f"# Container ID '{cntr_id}' found. Performing {command}...")
				return run_command(["docker", command, cntr_id], dbg_mode=DebugMode.REPORT_ONLY).returncode
			else:
				logger.info(f": Container '{CONTAINER_NAME}' is not running.")
		#
		elif command in ["start", "wstart"]:
			if get_container_id():
				logger.warning(f": Container '{CONTAINER_NAME}' is already running.")
				return 1
			cmd = ["docker", "run"] + docker_opts + ["--name", CONTAINER_NAME, "--detach", img_name]
			if command == "wstart":
				cmd += ["/bin/bash", "-c", "sleep infinity && wineserver -p"]
			else:
				cmd += ["sleep", "infinity"]
			return run_command(cmd, dbg_mode=DebugMode.REPORT_ONLY).returncode
		#
		elif command == "attach":
			if not get_container_id():
				logger.warning(f": Container '{CONTAINER_NAME}' is not running.")
				return 1
			cmd = ["docker", "exec", "--interactive", "--tty", CONTAINER_NAME, "sudo", "--login", "--user=user", "--"]
			return run_command(cmd + args_right, dbg_mode=DebugMode.REPORT_ONLY).returncode
		#
		elif command == "sshd":
			cache_dir = Path.home() / "tmp" / f"{CONTAINER_NAME}-cache"
			cache_dir.mkdir(parents=True, exist_ok=True)
			sshd_cmd = ["docker", "run"] + docker_opts + ["--name", CONTAINER_NAME, "--volume",
				f"{cache_dir}:/home/user/.cache:rw", "--detach", img_name, "sudo", "--", "/usr/sbin/sshd", "-e", "-D", "-p",
				str(SSHD_PORT)]
			if run_command(sshd_cmd, dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
				logger.info(f"# SSHD service started on port {SSHD_PORT}. Connect with 'ssh -p {SSHD_PORT} user@localhost'.")
			else:
				return 1
		#
		elif command == "run":
			return run_command(docker_command(docker_opts, img_name, args_right), dbg_mode=DebugMode.REPORT_ONLY).returncode
		#
		elif command == "versions":
			script: list[str] = CMAKE_LIB_SUBDIR + ["bin", "versions.sh"]
			target_script = os.path.join(RUN_DIR, *script)
			if not os.path.exists(target_script):
				logger.warning(f": Script '{os.path.join(*script)}' not found.")
				return 1
			# Form the path for execution inside the container.
			target_script = f"/mnt/project/{PROJECT_SUBDIR}/{'/'.join(script)}"
			return run_command(docker_command(docker_opts, img_name, ["bash", target_script]),
				dbg_mode=DebugMode.REPORT_ONLY).returncode
		else:
			# The default behavior is to execute the discovered build script.
			target_script = f"/mnt/project/{PROJECT_SUBDIR}/{self.script}"
			return run_command(docker_command(docker_opts, img_name, [target_script] + args_right),
				dbg_mode=DebugMode.REPORT_ONLY).returncode
		return 0


class SubCommandInstall(SubCommand):
	"""Subcommand handler for the 'create' command."""

	def __init__(self):
		super().__init__("install", ["i"])

	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		self.parser = subparsers.add_parser(self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Install required build tools or a quick start template project.")
		return self.parser

	def options(self, parser: argparse.ArgumentParser):
		"""Adds options to the given parser for the create command."""
		# Adds the standard help option.
		super().options(parser)
		# Configure the command line options.
		parser.add_argument("-p", "--project", action="store_true",
			help="Install the cmake project directories and files from the template repository.")
		choices: List[str] = ["tools", "mingw", "msvc", "msvc-alt"]
		if sys.platform != "win32":
			choices.append("doxygen")
		parser.add_argument("-t", "--toolchain", type=str, choices=choices,
			help="""Install a portable toolchains for in Windows or Wine with which the Qt library is build.
Choices are:
  tools    - Multiple tools as CMake, Ninja, NSIS and Git client for Wine(Linux Only).
  mingw    - MinGW x86_64 v13.2.0 posix + msvcrt compiler compatible with the Qt library.
  msvc     - MSVC 2022 x86_64 compatible with the Qt library preassembled from a Nexus repository.
  msvc-alt - MSVC 2022 x86_64 compatible with the Qt library from Microsoft itself. (Windows only)
  doxygen  - Doxygen latest released version. (Linux only)
""")
		choices: List[str] = []
		if sys.platform == "win32":
			choices.append("win")
		else:
			choices = ["dce", "dio", "lnx", "win"]
			if platform.processor() == 'x86_64':
				choices += ["arm", "qemu"]
		parser.add_argument("-r", "--required", type=str, choices=choices,
			help="""Install required packages using the Debian 'apt' package manager on Linux or 'WinGet' for Windows.
Choices are depended on the host platform:
  Linux:
    dce    - Install 'docker-ce' latest version using an external source.
    dio    - Install 'docker.io' package bundled with the distro.
    qemu   - Packages for running another architecture in a docker container.
    lnx    - Packages for architecture x86_64 or aarch64.
    arm    - Packages x86_64 for aarch64 GCC x86_64 cross-compile.
    win    - Packages x86_64 for Windows MinGW x86_64 cross-compile.
  Windows: 
    win - Windows WinGet packages for build tools except a compiler(s).
""")

	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str] | None) -> int:
		"""
		Handles the 'create' command execution of the script.
		:return: Exit code.
		"""
		# Call parent to handle the common dry-run option.
		super().handle(args, args_left, args_right)
		if args.required:
			if self.install_packages(args.required):
				return 1
		# Check if to create project items when requested.
		if args.project:
			if not self.create_project():
				return 1
		if args.toolchain:
			if not self.install_toolchain(args.toolchain):
				return 1
		return 0

	@staticmethod
	def install_toolchain(toolchain: str) -> bool:
		"""Installs toolchains."""

		def get_file_from_url(url: str, suffix: str = None) -> str | None:
			"""Copies the file from the url to a temporary file."""
			import requests
			with (tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp):
				try:
					req = requests.get(url, stream=True)
					if not req.ok:
						ex = FileNotFoundError(f"Failed to get file: {req.url}")
						ex.add_note(f"Reason: {req.status_code} {req.reason}")
						raise ex
					for chunk in req.iter_content(chunk_size=8192 * 16):
						tmp.write(chunk)
					return tmp.name
				finally:
					req.close()
					tmp.close()

		# Assemble the installation directory.
		install_dir = os.path.join(RUN_DIR, "lib", "toolchain")
		# When the installation directory is a symlink bailout.
		if os.path.islink(install_dir):
			logger.error(f": Installation directory '{install_dir}' is symlinked so it cannot be overwritten.")
			return False
		# Make sure it is fully created.
		os.makedirs(install_dir, exist_ok=True)
		match toolchain:
			case "tools":
				logger.info("# Installing Multiple tools as CMake, Ninja, NSIS and Git client for Wine.")
				zip_file = get_file_from_url(
					# This exact one is required in combination with Qt since it is build using this version.
					url="https://nexus.scanframe.com/repository/shared/library/toolchain/win-x86_64-cmake-4.2-combi.zip",
					suffix=".7z")
				if run_command([get_7z_exe(), "x", zip_file, f"-o{install_dir}/win-x86_64-cmake-4.2-combi", "-aos"],
					dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
					logger.error(f"! Failed to unzip file: {zip_file}")
					return False

			case "mingw":
				logger.info("# Installing MinGW x86_64 v13.2.0 posix + msvcrt compiler compatible with the Qt library.")
				zip_file = get_file_from_url(
					# This exact one is required in combination with Qt since it is build using this version.
					url="https://nexus.scanframe.com/repository/shared/library/toolchain/w64-x86_64-mingw-1320-posix.zip",
					suffix=".7z")
				if run_command([get_7z_exe(), "x", zip_file, f"-o{install_dir}", "-aos"],
					dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
					logger.error(f"! Failed to unzip file: {zip_file}")
					return False

			case "msvc":
				logger.info("# Installing MSVC 2022 x86_64 compatible with the Qt library. (preassembled)")
				zip_file = get_file_from_url(
					# This exact one is required in combination with Qt since it is build using this version.
					url="https://nexus.scanframe.com/repository/shared/library/toolchain/w64-x86_64-msvc-2022.zip", suffix=".zip")
				if run_command([get_7z_exe(), "x", zip_file, f"-o{install_dir}", "-aos"],
					dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
					logger.error(f"! Failed to unzip file: {zip_file}")
					return False

			case "msvc-alt":
				logger.info("# Installing MSVC 2022 x86_64 compatible with the Qt library.")
				# Download a python file for downloading the MSVC
				py_file = get_file_from_url(
					url="https://raw.githubusercontent.com/Scanframe/sf-cygwin-bin/refs/heads/master/portable-msvc.py",
					suffix=".py")
				if run_command([sys.executable, py_file, "--vs", "2022", "--target", "x64", "--accept-license"],
					cwd=install_dir, dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
					logger.error("! Failed to execute installer script.")
					return False

			case "doxygen":
				logger.info("# Installing Doxygen latest released version.")
				doxygen_dir = os.path.join(install_dir,  "doxygen")
				if os.path.exists(doxygen_dir):
					logger.warning(f": Doxygen directory already exists: {doxygen_dir}")
					return False
				release = get_github_release("doxygen", "doxygen", "*.linux.bin.tar.gz")
				if release["assets"]:
					extract_by_url(release["assets"][0]["url"], install_dir, "doxygen", release["assets"][0]["digest"])
				return False

		# Signal success.
		return True

	@staticmethod
	def create_project() -> bool:
		"""
		Creates and initializes a project by configuring Git, setting up basic files and directories,
		and incorporating a CMake submodule template. This function ensures that the required
		project structure is set up and optionally adds files or directories to a Git repository.
		:return: True indicates success and False indicates failure.
		"""
		# noinspection PyDeprecation
		if shutil.which("git") is None:
			logger.info("! Git is required and not installed run with option '--required' first!")
			return False
		# Assemble the git file or directory path.
		git_path = os.path.join(RUN_DIR, ".git")
		# Assemble the cmake/lib submodule directory path.
		dir_cmake_lib = str(os.path.join(*([RUN_DIR] + CMAKE_LIB_SUBDIR)))
		dir_tpl = os.path.join(RUN_DIR, dir_cmake_lib, "tpl")
		# Template files and their destinations.
		tpl_files = [("default.clang-format", [".clang-format"]), ("default.gitignore", [".gitignore"]),
			("git-pre-commit-hook.sh", [".git", "hooks", "pre-commit"]),  # ("user.cmake", ["user.cmake"]),
			("CMakePresets.json", ["CMakePresets.json"]), ("CMakeLists.cmake", ["CMakeLists.txt"]), ]
		# Template directories to copy from and to using lists.
		tpl_dirs = [(["cpack"], ["cmake", "cpack"])]
		# Check if Git is part of the project.
		if not os.path.exists(git_path):
			if ask_selection(options={True: "Yes", False: "No"}, title="Project is not a git repository!",
				caption="Initialize git repository?"):
				logger.info("# Initializing git repository...")
				if run_command(["git", "init", "--initial-branch=main"], dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
					logger.error("! Failed to initialize git repository with main branch!")
					return False
			else:
				logger.info("# Breaking by skipping git repository initialization.")
				return False
		# Check if the repository was installed 'cmake/lib' submodule.
		if not os.path.isdir(dir_cmake_lib):
			# Suggest installing the cmake project template.
			if ask_selection(options={True: "Yes", False: "No"}, title="CMakeLists.txt not found!",
				caption=f"Clone project helper in '{'/'.join(CMAKE_LIB_SUBDIR)}'?"):
				clone_options = {
					"main@https://github.com/Scanframe/sf-cmake.git": "GitHub Scanframe 'sf-cmake.git'",
					"main@https://git.scanframe.com/library/cmake-lib.git": "Scanframe GitLab 'cmake-lib.git'"
				}
				# Only add these options when '__DEV' is set.
				if RUN_ENV.get("__DEV"):
					clone_options["zipfile@https://www.scanframe.com/export/cmake-lib.zip"] = "Zipped (dev only)"
				if selected := ask_selection(
					options=clone_options,
					title="Project template repository?"):
					branch, repo = selected.split("@")
					if repo:
						if repo[-4:] == ".git":
							cmd = ["git", "clone", "--branch", branch, "--", repo, '/'.join(CMAKE_LIB_SUBDIR)]
							# cmd = ["git", "submodule", "add", "--branch", "main", "--", repo, '/'.join(CMAKE_LIB_SUBDIR)]
							if run_command(cmd, dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
								logger.error(f"! Failed to add submodule in '{'/'.join(CMAKE_LIB_SUBDIR)}'!")
								return False
						elif repo[-4:] == ".zip":
							with urlopen(repo) as response:
								# Use BytesIO to treat the downloaded bytes as a file-like object
								with zipfile.ZipFile(io.BytesIO(response.read()), 'r') as zf:
									for info in zf.infolist():
										extracted_path = zf.extract(info, RUN_DIR)
										# Only attempt to restore Unix permissions if on a Unix-like system
										if sys.platform != "win32" and info.create_system == 3:
											unix_attributes = info.external_attr >> 16
											if unix_attributes > 0:
												try:
													os.chmod(extracted_path, unix_attributes)
												except OSError:
													# Handle cases where chmod might fail (e.g., read-only filesystem)
													pass
					else:
						logger.info("# Breaking by skipping git submodule '{'/'.join(CMAKE_LIB_SUBDIR)}' installation.")
						return False
		# Check if the git submodule was installed and the template root is available.
		if os.path.isdir(dir_cmake_lib):
			# Add all directories from the tpl directory.
			for d in [d for d in os.listdir(os.path.join(dir_tpl, "root")) if
				os.path.isdir(os.path.join(dir_tpl, "root", d))]:
				tpl_dirs.append((["root", d], [d]))
			if ask_selection(options={True: "Yes", False: "No"},
				title="Clone/copy CMake Submodule as Helper & Template Project",
				caption="Copy into the project root when not existing?"):
				# Iterate through all subdirectories in the cmake/lib submodule template root directory.
				for entry in tpl_dirs:
					# Assemble the full path of the destination subdirectory.
					dir_dest = os.path.join(RUN_DIR, *entry[1])
					# Check if the destination subdirectory already exists and skip it if it does.
					if os.path.exists(dir_dest):
						logger.info(f"# Skipping subdirectory '{dir_dest}' since it exists already.")
					else:
						dir_src = os.path.join(dir_tpl, *entry[0])
						logger.info(f"# Copying subdirectory '{dir_dest}' into the project root directory.")
						if not DEBUG_FLAG:
							if os.path.isdir(dir_src):
								shutil.copytree(dir_src, dir_dest, dirs_exist_ok=False)
							else:
								logger.warning(f": Source directory copytree '{dir_src}' missing.")
						else:
							logger.debug(f"~ Not copying dir tree from '{dir_src}'")
				# Iterate through all the files with their final destinations.
				for entry in tpl_files:
					# From the source filepath.
					src_file = os.path.join(dir_tpl, "root", entry[0])
					# Form the actual destination filepath.
					dst_file = os.path.join(RUN_DIR, *entry[1])
					# Check if the destination file already exists and skip it if it does.
					if os.path.exists(dst_file):
						logger.info(f"# Skipping file '{os.path.join(*entry[1])}' since it exists already.")
					else:
						logger.info(f"# Copying file '{entry[0]}' into '{os.path.join(*entry[1])}'.")
						if not DEBUG_FLAG:
							if os.path.isfile(src_file):
								shutil.copy(src_file, dst_file)
							else:
								logger.warning(f": Source file copy '{src_file}' missing.")
						else:
							logger.debug(f"~ Not copying file '{src_file}'")
				if ask_selection(options={True: "Yes", False: "No"},
					title="Add directories and files and to the Git repository", caption="Add to Git repository?"):
					for entry in tpl_dirs:
						# Assemble the full path of the destination subdirectory.
						dest = str(os.path.join(*entry[1]))
						if not os.path.isdir(os.path.join(RUN_DIR, dest)):
							logger.warning(f": Directory '{dest}'  does not exist.")
						else:
							logger.info(f"# Adding directory '{dest}' to git repository.")
							if run_command(["git", "add", dest], dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
								logger.error(f"! Git failed to add directory '{dest}'.")
					for entry in tpl_files:
						# Assemble the full path of the destination file.
						dest = str(os.path.join(*entry[1]))
						if not os.path.isfile(os.path.join(RUN_DIR, dest)):
							logger.warning(f": File '{dest}'  does not exist.")
						else:
							logger.info(f"# Adding file '{dest}' to git repository.")
							if run_command(["git", "add", dest], dbg_mode=DebugMode.REPORT_ONLY).returncode != 0:
								logger.error(f"! Git failed to add file '{dest}'.")
		return True

	@staticmethod
	def install_packages(target: str) -> None:
		"""Installs the necessary packages depending on the environment Linux or Windows."""
		logger.info(f"About to install required packages for ({target})...")
		# Prefix the target with the system name.
		target = sys.platform + '/' + target
		logger.info(f"# Target: {target}")
		# noinspection PyBroadException
		try:
			if target == "linux/wine":
				with zipfile.ZipFile('r') as zip_object:
					zip_object.extractall(path="dest-dir")
			elif target == "linux/dio":
				# noinspection PyDeprecation
				if shutil.which("docker"):
					logger.warning(f"# Command 'docker' command is already available.")
					return
				run_command(
					["sudo", "apt-get", "--yes", "install", "docker.io"], dbg_mode=DebugMode.REPORT_ONLY)
			elif target == "linux/dce":
				# Check if the 'docker' command exists.
				# noinspection PyDeprecation
				if shutil.which("docker"):
					logger.warning(f"# Command 'docker' command is already available.")
					return
				# Destination of the Docker sources-file.
				sources_file = "/etc/apt/sources.list.d/docker-ce.sources"
				if os.path.exists(sources_file):
					logger.warning(f"# Docker source-file '{sources_file}' already exists?!")
					return
				#
				logger.info(f"# Installing docker target.")
				# Get distribution information
				distro = run_command(["lsb_release", "-is"], capture_output=True, dbg_mode=DebugMode.SILENT).stdout.decode("utf-8").strip().lower()
				codename = run_command(["lsb_release", "-cs"], capture_output=True, dbg_mode=DebugMode.SILENT).stdout.decode("utf-8").strip()
				arch = run_command(["dpkg", "--print-architecture"], capture_output=True, dbg_mode=DebugMode.SILENT).stdout.decode("utf-8").strip()
				# Download GPG key
				gpg_url = f"https://download.docker.com/linux/{distro}/gpg"
				gpg_result = run_command(["wget", "-qO-", gpg_url], capture_output=True, dbg_mode=DebugMode.SILENT)
				if gpg_result.returncode != 0:
					logger.error(f"! Failed to download Docker GPG key from {gpg_url}")
				else:
					gpg_key = gpg_result.stdout.decode("utf-8")
					# Indent GPG key lines with a space
					gpg_key_indented = "\n".join(" " + line for line in gpg_key.splitlines())
					# Create Docker sources file content
					docker_sources = f"""Types: deb
URIs: https://download.docker.com/linux/{distro}
Suites: {codename}
Components: stable
Architectures: {arch}
Signed-By:
{gpg_key_indented}
"""
					run_command(["sudo", "tee", sources_file], input_data=docker_sources.encode(), dbg_mode=DebugMode.REPORT_ONLY)
					run_command(["sudo", "apt-get", "update"], dbg_mode=DebugMode.REPORT_ONLY)
					run_command(["sudo", "apt-get", "--yes", "upgrade"], dbg_mode=DebugMode.REPORT_ONLY)
					# Install Docker CE and add the user to the 'docker' group.
					run_command(["sudo", "apt", "install", "-y", "docker-ce"], dbg_mode=DebugMode.REPORT_ONLY)
					if username := os.environ.get("USER", ""):
						run_command(["sudo", "usermod", "-aG", "docker", username], dbg_mode=DebugMode.REPORT_ONLY)
						logger.info(f"# Added user '{username}' to the 'docker' group.")

			elif target == "linux/lnx":
				# Initial updates and prerequisites
				run_command(["sudo", "apt-get", "update"], dbg_mode=DebugMode.REPORT_ONLY)
				run_command(["sudo", "apt-get", "--yes", "upgrade"], dbg_mode=DebugMode.REPORT_ONLY)
				run_command(
					["sudo", "apt-get", "--yes", "install", "wget", "curl", "gpg", "lsb-release", "software-properties-common",
						"ccache", "python3", "python3-venv", "python3-dev", "python3-pefile", "python3-pyelftools",
						"python-is-python3"], dbg_mode=DebugMode.REPORT_ONLY)
				# XCB and Qt6 dependencies
				# noinspection SpellCheckingInspection
				xcb_pkgs = ["xcb", "libxkbcommon-x11-0", "libxcb-xinput0", "libxcb-cursor0", "libxcb-shape0", "libxcb-icccm4",
					"libxcb-image0", "libxcb-keysyms1", "libxcb-render-util0", "libpcre2-16-0"]
				run_command(["sudo", "apt-get", "--yes", "install"] + xcb_pkgs, dbg_mode=DebugMode.REPORT_ONLY)
				# LLVM Repository check and add
				repo_list = run_command(["apt-add-repository", "--list"], shell=False, capture_output=True,
					dbg_mode=DebugMode.SILENT).stdout.decode("utf-8")
				# if not re.findall(r'^Suites:\s+llvm-toolchain', repo_list, re.MULTILINE):
				# 	# Use shell=True for complex pipe operations
				# 	run_command(
				# 		["wget https://apt.llvm.org/llvm-snapshot.gpg.key -O - | sudo tee /etc/apt/trusted.gpg.d/apt.llvm.org.asc >/dev/null"],
				# 		shell=True)
				# 	codename = run_command(["lsb_release", "-sc"], capture_output=True,
				# 		dbg_mode=DebugMode.SILENT).stdout.decode("utf-8").strip()
				# 	repo_url = f"deb https://apt.llvm.org/{codename}/ llvm-toolchain-{codename} main"
				# 	run_command(["sudo", "apt-add-repository", "--yes", "--no-update", repo_url])
				# Kitware Repository (Ubuntu only)
				if not len(re.findall(r'apt\.kitware\.com/ubuntu', repo_list, re.MULTILINE)):
					distro = run_command(["lsb_release", "-is"], capture_output=True, dbg_mode=DebugMode.SILENT).stdout.decode(
						"utf-8").strip()
					if distro == 'Ubuntu':
						run_command(
							["wget -O - https://apt.kitware.com/keys/kitware-archive-latest.asc 2>/dev/null | gpg --dearmor - | sudo tee /etc/apt/trusted.gpg.d/kitware.gpg >/dev/null"],
							shell=True, dbg_mode=DebugMode.REPORT_ONLY)
						codename_cs = run_command(["lsb_release", "-cs"], capture_output=True).stdout.decode("utf-8").strip()
						run_command(["sudo", "apt-add-repository", "--yes", "--no-update",
							f"deb https://apt.kitware.com/ubuntu/ {codename_cs} main"], dbg_mode=DebugMode.REPORT_ONLY)
					else:
						logger.info("# Cannot install latest 'cmake' from Kitware since this in no Ubuntu distribution.")
				# Final updates and main package installation
				run_command(["sudo", "apt-get", "update"], dbg_mode=DebugMode.REPORT_ONLY)
				run_command(["sudo", "apt-get", "--yes", "upgrade"], dbg_mode=DebugMode.REPORT_ONLY)
				# noinspection SpellCheckingInspection
				main_pkgs = ["make", "cmake", "ninja-build", "gcc", "g++", "doxygen", "graphviz", "libopengl0",
					"libgl1-mesa-dev", "libglu1-mesa-dev", "libxkbcommon-dev", "libxkbfile-dev", "libvulkan-dev", "libssl-dev",
					"default-jre-headless", "chrpath", "clang-format"]
				run_command(["sudo", "apt-get", "--yes", "install"] + main_pkgs, dbg_mode=DebugMode.REPORT_ONLY)

			elif target == "linux/qemu":
				run_command(["sudo", "apt-get", "install", "-y", "qemu-user-static", "binfmt-support", "qemu-user-binfmt"], dbg_mode=DebugMode.REPORT_ONLY)

			elif target == "linux/win":
				run_command(["sudo", "apt-get", "install", "-y", "mingw-w64"], dbg_mode=DebugMode.REPORT_ONLY)
				# Check if wine is installed using shutil.which (cleaner than command -v)
				# noinspection PyDeprecation
				if not shutil.which("wine"):
					run_command(["sudo", "apt-get", "--yes", "install", "wine"], dbg_mode=DebugMode.REPORT_ONLY)

			elif target == "linux/arm":
				run_command(["sudo", "apt-get", "--yes", "install", "gcc-aarch64-linux-gnu", "g++-aarch64-linux-gnu",
					"binutils-aarch64-linux-gnu"])
				arch_check = run_command(["dpkg", "--print-foreign-architectures"], capture_output=True,
					dbg_mode=DebugMode.SILENT).stdout
				if "arm64" in arch_check.splitlines():
					# noinspection SpellCheckingInspection
					arm_pkgs = ["gcc-aarch64-linux-gnu:amd64", "g++-aarch64-linux-gnu:amd64", "binutils-aarch64-linux-gnu:amd64",
						"libgles-dev:arm64", "libegl-dev:arm64", "libgl-dev:arm64", "libpcre2-16-0:arm64", "libglvnd-dev:arm64",
						"libpng16-16t64:arm64", "xcb:arm64", "libxkbcommon-x11-0:arm64", "libxcb-xinput0:arm64",
						"libxcb-cursor0:arm64", "libxcb-shape0:arm64", "libxcb-icccm4:arm64", "libxcb-image0:arm64",
						"libxcb-keysyms1:arm64", "libxcb-render-util0:arm64", "libdbus-1-3:arm64", "libcairo-gobject2:arm64",
						"libxkbcommon-dev:arm64", "libxkbfile-dev:arm64"]
					run_command(["sudo", "apt-get", "--yes", "install"] + arm_pkgs, dbg_mode=DebugMode.REPORT_ONLY)
				else:
					logger.info("Architecture 'arm64' is not enabled and packages are therefore not installed!")

			elif target == "win32/win" or target == "cygwin/win":
				# Install only for Windows non-standard packages using pip.
				for pkg in ["pefile", "pyelftools", "requests"]:
					if subprocess.run([sys.executable, "-m", "pip", "show", pkg], stdout=subprocess.DEVNULL,
						stderr=subprocess.DEVNULL).returncode == 0:
						logger.info(f"- Pip package '{pkg}' is already installed.")
					else:
						logger.info(f"- Installing pip package '{pkg}'.")
						if subprocess.run([sys.executable, "-m", "pip", "install", pkg]).returncode > 0:
							logger.error(f"! Failed to install Python package '{pkg}'!")
				# WinGet packages to install.
				wg_pkgs = {
					"Git": "Git.Git",
					"7-Zip": "7zip.7zip",
					"CMake C++ build tool": "Kitware.CMake",
					"Ninja build system": "Ninja-build.Ninja",
					"Nullsoft Install System": "NSIS.NSIS",
					"Oracle JRE": "Oracle.JavaRuntimeEnvironment",
					"LLVM Clang-Format": "LLVM.ClangFormat",
					"Doxygen": "DimitriVanHeesch.Doxygen",
					# TODO: Sadly, the WinGet package is missing some MinGW DLL's. The official installer does not.
					# "Graphviz": "Graphviz.Graphviz"
					"!Graphviz": "https://gitlab.com/api/v4/projects/4207231/packages/generic/graphviz-releases/14.1.2/windows_10_cmake_Release_graphviz-install-14.1.2-win64.exe"
				}
				for name, pkg_id in wg_pkgs.items():
					if name[:1] == "!":
						logger.warning(f": Install '{name[1:]}' manually from URL '{pkg_id}'!")
						continue
					# Check if installed - using a specific check to avoid exception on "not found"
					check_installed = run_command(
						["winget", "list", "--disable-interactivity", "--accept-source-agreements", "--exact", "--id", pkg_id],
						capture_output=True, check=False, dbg_mode=DebugMode.SILENT)
					if check_installed.returncode == 0:
						logger.info(f"- WinGet Package '{name}' already installed.")
					else:
						logger.info(f"- Installing WinGet package '{name}' ...")
						run_command(
							["winget", "install", "--disable-interactivity", "--accept-source-agreements", "--exact", "--id", pkg_id],
							dbg_mode=DebugMode.REPORT_ONLY)
				# When the apt-cyg shell script is found, install also the Cygwin packages.
				# noinspection PyDeprecation
				if target == "cygwin/win" and shutil.which("apt-cyg") is not None:
					# Cygwin Packages
					cg_pkgs = ["dialog", "recode", "perl-Image-ExifTool", "graphviz", "pcre", "jq", "unzip", "colordiff",
						"dos2unix"]
					for pkg in cg_pkgs:
						try:
							run_command(["apt-cyg", "install", pkg], dbg_mode=DebugMode.REPORT_ONLY)
						except subprocess.CalledProcessError:
							logger.exception(
								"Failed to install 1 or more Cygwin packages (Try the Cygwin setup tool when elevation is needed)!")
							sys.exit(1)
			else:
				logger.error(f"Invalid requirements target '{target}', see help for valid ones!")
				sys.exit(1)
		except subprocess.CalledProcessError as ex:
			# logger.exception automatically includes the stack trace (exc_info=True)
			logger.exception(f"! Failed to install 1 or more packages due to a command failure.")
			raise ex
		except Exception as ex:
			logger.exception(f"! An unexpected error occurred during package installation.")
			raise ex


class SubCommandRun(SubCommand):
	"""Subcommand handler for the 'create' command."""

	def __init__(self):
		super().__init__("run", ["r"])

	def create_parser(self, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
		self.parser = subparsers.add_parser(self.command, aliases=self.aliases, add_help=False,
			formatter_class=argparse.RawTextHelpFormatter,
			help="Runs an executable with the environment from given configure preset.")
		self.parser.epilog = f"""
Examples:

  List files in the configure preset's binary directory:
    Linux: 
      ./{self.script} {self.command} -p gnu-debug
    Windows:
      {self.script} {self.command} -p mingw-debug
      
  Run executable in with the working directory as the binary: 
    Linux: 
      ./{self.script} {self.command} -p gnu-debug
      ./{self.script} {self.command} -p gnu-debug -- ./hello-world.bin
    Windows:
      ./{self.script} {self.command} -p msvc-debug -- hello-world.exe
      ./{self.script} {self.command} -p gw-debug -- cmd /c echo %PATH%
      
  Execute command without the cmake environment: 
      {self.script} --exec -- cl
      {self.script} --exec -- gcc --version
      {self.script} --preset gnu-debug -- cmd /c echo ^%PATH^%
"""
		return self.parser

	def options(self, parser: argparse.ArgumentParser):
		"""Adds options to the given parser for the create command."""
		# Adds the standard help option.
		super().options(parser)
		# Configure the command line options.
		parser.add_argument("-p", "--preset", type=str, nargs="?", required=True, metavar="<preset>",
			help="The configure preset providing for the environment and working directory.")
		parser.add_argument("-e", "--exec", action="store_true", help="Execute command without the cmake set environment.")
		parser.add_argument("-v", "--verbose", action="store_true",
			help="Shows information when the command is executed for error analysis.")

	def handle(self, args: argparse.Namespace, args_left: List[str], args_right: List[str]) -> int:
		"""
		Handles the 'create' command execution of the script.
		:return: Exit code.
		"""
		# Call parent to handle the common dry-run option.
		super().handle(args, args_left, args_right)
		# When no command is given, list the files in the directory.
		if not len(args_right):
			# When executing from Linux and the Windows cross-compiler is used.
			if sys.platform != "win32" and not args.exec and get_compiler_type(args.preset, PresetTypes.CONFIGURE) == "gw":
				args_right = ["cmd", "/c", "dir", "/a"]
			elif sys.platform == "win32":
				args_right = ["cmd", "/c", "dir", "/a"]
			else:
				args_right = ["ls", "-la"]
		# Toolchain environment by preset and bailout when not set.
		if not set_environment_by_preset(args.preset, PresetTypes.CONFIGURE):
			return 1
		# Check if an application is to be executed.
		if args.exec:
			# Check if the preset was found.
			preset = get_preset_by_name(PresetTypes.CONFIGURE, args.preset)
			# Get the binary directory from preset expanding then macros.
			bin_dir = expand_macros(preset, preset.get("environment", {}).get("SF_EXECUTABLE_DIR"), True)
			env = preset.get("environment", {})
			for var in env:
				RUN_ENV[var] = expand_macros(preset, env.get(var), context=env)
			cmake_bin_dir = expand_macros(preset,
				preset.get("cacheVariables", {}).get("CMAKE_RUNTIME_OUTPUT_DIRECTORY", {}).get("value"), True)
			logger.debug(f"~ Working directory set as 'CMAKE_RUNTIME_OUTPUT_DIRECTORY' to: {cmake_bin_dir}")
			if bin_dir is None:
				logger.error(f"! Field 'binaryDir' not found for configure preset '{args.preset}'.")
				return 1
			return run_command(args_right, cwd=bin_dir, dbg_mode=DebugMode.REPORT_ONLY).returncode
		else:
			# Holds the cmake script and raise an exception on failure.
			cmake_script = get_config_section("config", fail=True).get("cmake-run-file", os.path.join(*(CMAKE_LIB_SUBDIR + ["run-executable.cmake"])))
			# Check if the required cmake script is present and if not, bailout.
			if not os.path.exists(cmake_script):
				logger.info(f": Sub command 'run' disabled due to missing '{cmake_script}' file.")
				return 1
			# Preset is required, so no check there.
			cmd = ["cmake", "--preset", args.preset, f"-DSF_EXECUTABLE={self.cmake_encode(args_right)}"]
			if args.verbose:
				cmd += [f"-DSF_VERBOSE=ON"]
			cmd += ["-P", cmake_script]
			return run_command(cmd, dbg_mode=DebugMode.REPORT_ONLY).returncode

	@staticmethod
	def cmake_encode(args: List[str]) -> str:
		"""
		Encodes only the characters ';', '/', ':', '=', '?' and '%,'
		which matches the custom argument decode logic in CMake.
		"""
		# Mapping of characters to their hex codes where '%' must be first to avoid double-encoding the '%' in '%3B', etc.
		replacements = [("%", "%25"), (";", "%3B"), (" ", "%20")]
		encoded = []
		for entry in args:
			for char, hex_code in replacements:
				entry = entry.replace(char, hex_code)
			encoded.append(entry)
		return ";".join(encoded)


def split_arguments(arguments: List[str], split_arg: str = "--") -> tuple[List[str], List[str]]:
	"""
	Splits the arguments in a left and right
	:param arguments:
	:param split_arg:
	"""
	# Get the separator index of an argument.
	arg_sep_idx = arguments.index(split_arg) if "--" in arguments else -1
	args_left = arguments[:arg_sep_idx] if arg_sep_idx > 0 else arguments
	args_right = arguments[arg_sep_idx + 1:] if len(arguments) > arg_sep_idx > 0 else []
	return args_left, args_right


def main() -> int:
	"""
	Main entry point for the build script.
	:return: Exit code.
	"""
	# Get the script's name.
	script = os.path.basename(__file__)
	# Strip other first argument which is the script itself.
	arguments = sys.argv[1:]
	# Register the commands.
	std_cmd: SubCommand = SubCommandNative().register()
	# Only when not in Windows
	if sys.platform != "win32":
		# And also not in 'Wine' register the command only for an x86_64 architecture.
		if not is_wine() and platform.processor() == "x86_64":
			SubCommandWine().register()
		# And also not in Docker register the command.
		if not is_docker() and sys.platform != "win32":
			SubCommandDocker().register()
	# Register unconditional commands.
	SubCommandInstall().register()
	SubCommandRun().register()
	#
	parser = argparse.ArgumentParser(description="""Helper for running CMake , CTest, CPack commands using 'CMakePresets.json' and 'CMakeUserPresets.json'.
Running Native, Docker, Wine and nested as in Docker > Wine.
""", formatter_class=argparse.RawTextHelpFormatter, add_help=False)
	# Get the ini file.
	ini_file = str(os.path.splitext(script)[0] + ".ini")
	parser.epilog = f"""
The script depends on the configuration file '{ini_file}' which contains sections
for creating environments for each nested call of this script.

To Build and test the example project:

  On Linux:
    ./{script} i -r lnx                    # Required packages for Linux (Debian only).
    ./{script} i -p                        # Clone the cmake-lib repository and copy the sample project.
    ./{script} -bt gnu-debug               # Build and test a preset local.
    ./{script} run -p gnu-debug -- ./<exe> # Execute an application from the presets' output directory.
    ./{script} d -- w -- -bt msvc-debug    # Preset make, build and test from Wine in Docker.
    ./{script} d -- w -- run -p msvc-debug hello-world.exe # Run an application form the output in Docker/Wine.
    ./{script} d versions                  # Report all versions within the Docker image.
    ./{script} d -- -b gnu-debug -N        # Build a target select from a menu (e.g. 'document' for DoxyGen).
    ./{script} d -- -w gnu-debug           # Run a preset configured workflow including packaging mostly used in pipelines.
    ./{script} d start/stop                # Start or stop the Docker container as daemon to speed up.

  On Windows:
    {script} i -r win                      # Required packages (WinGet/Pip) for Windows.
    {script} i -p                          # Clone the cmake-lib repository and copy the sample project.
    {script} i -t msvc                     # Install the MSVC toolchain.
    {script} -bt msvc-debug                # Preset make, build and test.
    {script} run -p msvc-debug -- hello-world.exe
    {script} run -p msvc-debug -- hello-world-qt.exe
"""
	# Subparsers for command-specific arguments
	subparsers = parser.add_subparsers(dest="subcmd", help=f"Subcommand defaulting to '{std_cmd.command}' when omitted.")
	# Create subparsers for all registered commands.
	for sub_cmd in SubCommand.registry:
		cmd = SubCommand.registry[sub_cmd]
		cmd.options(cmd.create_parser(subparsers))
	# Show help when no arguments are passed on the command line.
	if len(arguments) == 0:
		parser.print_help()
		return 0
	# When the first argument is not a subcommand insert the standard command.
	if len(arguments) and arguments[0] not in parser._actions[0].choices:
		arguments = [std_cmd.command] + arguments
	# When only the command is given show its help.
	if len(arguments) == 1:
		if arguments[0] in SubCommand.registry:
			SubCommand.registry[arguments[0]].print_help()
			return 0
		for cmd in SubCommand.registry:
			if arguments[0] in SubCommand.registry[cmd].aliases:
				SubCommand.registry[cmd].print_help()
				return 0
	# To circumvent the exit by the parser.
	try:
		args_left, args_right = split_arguments(arguments)
		# Parse the command line arguments left of '--'.
		args = parser.parse_args(args_left)
		if args.subcmd in SubCommand.registry:
			return SubCommand.registry[args.subcmd].handle(args, args_left, args_right)
		for cmd in SubCommand.registry:
			if args.subcmd in SubCommand.registry[cmd].aliases:
				return SubCommand.registry[cmd].handle(args, args_left, args_right)
	except HelpAction.HelpException:
		return 0
	return 0


if __name__ == "__main__":
	"""Main entry point for the script."""
	exitcode = 0
	try:
		# Change to the directory of this script.
		os.chdir(RUN_DIR)
		exitcode = main()
		origin = [sys.platform]
		if is_docker():
			origin.append(f"Docker({platform.processor()})")
		if is_wine():
			origin.append("Wine")
		logger.info(f"- {os.path.basename(__file__)} ({'>'.join(origin)}), executed in {int(time.time() - start_time)}s.")
	except KeyboardInterrupt:
		logger.info("! Interrupted by user.")
		exitcode = 130
	except subprocess.CalledProcessError as cmd_ex:
		if cmd_ex.returncode != 130:
			logger.error(f"! Command error({cmd_ex.returncode}): {' '.join(cmd_ex.cmd)}")
			if cmd_ex.stdout:
				logger.error(cmd_ex.stdout.decode("utf-8"))
			if cmd_ex.stderr:
				logger.error(cmd_ex.stderr.decode("utf-8"))
		exitcode = cmd_ex.returncode
	except Exception as any_ex:
		logger.error(f"! Exception({any_ex.__class__.__name__}): {any_ex}")
		if hasattr(any_ex, '__notes__'):
			for note in any_ex.__notes__:
				logger.error(f"Note: {note}")
		exitcode = 1
	# Show the cursor again.
	sys.exit(exitcode)
