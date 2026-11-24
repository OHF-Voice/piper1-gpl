#!/usr/bin/env python3
# coding=utf-8
"""
Library Installer and Extractor

Installs the cmake-lib repository into the 'cmake/lib' directory
at a specified tag (defaults to 'latest').
"""

from __future__ import annotations
import argparse
from typing import List, Any, Dict, Optional
import subprocess
import sys
import urllib.request
from pathlib import Path
import tarfile

# Default repository URL and tag
REPO_URL = "https://github.com/scanframe-org/sf-cmake.git"
DEFAULT_TAG = "latest"
TARGET_DIR = Path("cmake/lib")


def do_clone(args: argparse.Namespace) -> int:
	"""Clone the repository if the target directory does not yet exist."""
	if TARGET_DIR.exists():
		print(f"Directory '{TARGET_DIR}' already exists, cloning skipped.")
		return 0
	# Create parent directory if needed
	TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
	# Clone the repository at the specified tag
	print(f"Cloning {REPO_URL} at tag {args.tag} into {TARGET_DIR}...")
	result = subprocess.run(
		["git", "clone", "--branch", args.tag, "--single-branch", REPO_URL, str(TARGET_DIR)],
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		print(f"Error: git clone failed.\n{result.stderr}", file=sys.stderr)
		return result.returncode
	print(f"Successfully cloned cmake-lib at tag {args.tag}.")
	return 0


def do_extract(args: argparse.Namespace) -> int:
	"""Download a tar.gz archive from GitHub and extract it into the target directory."""
	if TARGET_DIR.exists():
		print(f"Directory '{TARGET_DIR}' already exists, extraction skipped.")
		return 0
	# Build the GitHub tar.gz URL from the repo URL and tag.
	repo_url = REPO_URL.rstrip("/").rstrip(".git")
	tar_url = f"{repo_url}/archive/refs/tags/{args.tag}.tar.gz"
	# Create parent directory if needed
	TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
	# Download the tar.gz file
	tar_path = TARGET_DIR.parent / f"sf-cmake-{args.tag}.tar.gz"
	print(f"Downloading {tar_url}...")
	try:
		urllib.request.urlretrieve(tar_url, str(tar_path))
	except urllib.error.URLError as e:
		print(f"Error: Failed to download tar.gz file.\n{e}", file=sys.stderr)
		return 1
	# Extract the tar.gz file
	print(f"Extracting to {TARGET_DIR.parent}...")
	try:
		with tarfile.open(tar_path, "r:gz") as tf:
			tf.extractall(TARGET_DIR.parent)
	except Exception as e:
		print(f"Error: Failed to extract tar.gz file.\n{e}", file=sys.stderr)
		tar_path.unlink(missing_ok=True)
		return 1
	# Clean up the tar.gz file
	tar_path.unlink()
	# The extracted folder is named sf-cmake-{tag}, rename it to the target name
	extracted_dir = TARGET_DIR.parent / f"sf-cmake-{args.tag}"
	if extracted_dir.exists():
		extracted_dir.rename(TARGET_DIR)
	else:
		print(f"Error: Expected extracted directory '{extracted_dir}' not found.", file=sys.stderr)
		return 1
	print(f"Successfully extracted cmake-lib at tag {args.tag}.")
	return 0


# Create symlink to build.py in project root
def do_create_symlink() -> int:
	"""Create a symlink from the project root to cmake/lib/bin/build.py.
	If the symlink already exists and points to the correct target, treat it as success.
	"""
	build_py_target = TARGET_DIR / "bin" / "build.py"
	symlink_path = Path("build.py")
	if not build_py_target.exists():
		print(f"Error: Target '{build_py_target}' does not exist. Cannot create symlink.", file=sys.stderr)
		return 1
	# Check if symlink already exists and points to the correct target
	if symlink_path.is_symlink():
		try:
			if symlink_path.resolve() == build_py_target.resolve():
				print(f"Symlink 'build.py' already exists and is valid.")
				return 0
		except OSError:
			pass
	# Remove existing symlink or file if present
	if symlink_path.exists() or symlink_path.is_symlink():
		symlink_path.unlink()
	symlink_path.symlink_to(build_py_target)
	print(f"Created symlink 'build.py' -> '{build_py_target}'.")
	return 0


def split_arguments(arguments: List[str], split_arg: str = "--") -> tuple[List[str], List[str]]:
	"""
	Splits the arguments in a left and right
	:param arguments:
	:param split_arg:
	"""
	# Get the separator index of an argument.
	arg_sep_idx = arguments.index(split_arg) if split_arg in arguments else -1
	args_left = arguments[:arg_sep_idx] if arg_sep_idx >= 0 else arguments
	args_right = arguments[arg_sep_idx + 1:] if len(arguments) > arg_sep_idx >= 0 else []
	return args_left, args_right


# Main entry point
def main() -> int:
	# Parser instance for reuse
	parser = argparse.ArgumentParser(
		description="Use the sf-cmake library repository at a specific tag.",
		formatter_class=argparse.RawTextHelpFormatter
	)
	parser.add_argument(
		"-c",
		"--clone",
		action="store_true",
		help="Use cloning instead of extraction for the repository.",
	)
	parser.add_argument(
		"-t",
		"--tag",
		default=DEFAULT_TAG,
		help=f"Repository tag to clone (default: {DEFAULT_TAG}).",
	)
	parser.epilog = """
	Arguments passed after '--' is passed to a call to 'build.py project <args>'.

	examples:
		 sf-cmake -- <args>               # Use 'latest' tag by default.
		 sf-cmake -c -t v1.0.0 -- <args>  # Use 'v1.0.0' tag.
	"""
	# Strip other first argument which is the script itself.
	arguments = sys.argv[1:]
	args_left, args_right = split_arguments(arguments)
	args = parser.parse_args(args_left)
	# Show help if no action flag is provided
	if not arguments:
		parser.print_help()
		return 0
	# Extract by default if not already present.
	if rc := (do_clone(args) if args.clone else do_extract(args)) != 0:
		return rc
	if rc := do_create_symlink():
		return rc
	# Run 'build.py project'.
	cmd: List[str] = ["build.py", "project"] + args_right
	return subprocess.run([sys.executable] + cmd, capture_output=False, text=True).returncode


if __name__ == "__main__":
	sys.exit(main())
