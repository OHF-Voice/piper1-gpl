# Agent Instructions: C++ Project

## Overview

This is a modern cross-platform build environment test project with CMake for Docker, Wine, native Linux and native
Windows.  
It is used to test the build environment for C++ projects. Qt6 only uses up to C++17. License: GNU General Public
License v3.0 (GPL-3.0).

## Commands

### Configuring, Building, Testing

All targets are built from the command line using the single command `./build.py`. When run without arguments, it will
show the help to build using a given toolchain.

## Boundaries

### Mandatory Git Tracking Policy

- **Strict Scope**: The "Project" consists **ONLY** of files currently tracked by Git.
- **Prohibition**: You **MUST NOT** read, reference, modify, or execute any file that is not tracked by Git.
- **Treat as Non-Existent**: Even if a file is visible in directory listings or returned by search tools, you **MUST**
  treat it as non-existent if it is untracked.
- **Verification Requirement**: Before interacting with any file, you **MUST** verify its status (e.g., using
  `git ls-files --error-unmatch <path>`). If the command fails, the file is out of bounds.

### Mandatory Code Formatting Policy

- **Strict Compliance**: All code must be formatted using `clang-format` with the provided configuration file.
- **Verification Requirement**: Before submitting any code changes, you **MUST** verify that the code adheres to the
  formatting rules by running `clang-format` on the modified files.

### Operational Safety Guardrails:

- **Always do**: Use smart pointers (`std::unique_ptr`, `std::shared_ptr`) for general resource management.
- **Always do**: Adhere strictly to RAII practices.
- **Never do**: Do not bypass explicit `noexcept` specifications on move constructors.

### Standards & Patterns

- **Header Guards**: Always use `#pragma once`.
- **Doxygen**: Use Doxygen-style comments in header files only.

### Naming Conventions

Key points:

- **Classes/Structs**: PascalCase.
- **Methods**: camelCase.
- **Members**: _camelCase (leading underscore).
- **Arguments/Variables**: lower_snake_case.

### Mandatory Commit Style

Conventional commits are preferred as described
by [www.conventionalcommits.org](https://www.conventionalcommits.org/en/v1.0.0/).
