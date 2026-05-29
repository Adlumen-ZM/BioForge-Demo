# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PepClaw is an agentic framework for bio-references and bio-data mining. It is currently in early development — design specifications are complete but source code has not yet been implemented.

## Repository State

- **Branch**: Development work happens on the `Yi` branch; `main` is the base branch for PRs.
- **Design docs**: `Design_doc/` contains Chinese-language PDF specifications:
  - `v0.1 Text Agent 技术方案.pdf` — Technical architecture for the Text Agent component
  - `v0.1 业务数据库设计方案.pdf` — Business database schema design
- **License**: Apache 2.0

## Architecture (from design docs)

The system is planned around two main components:

1. **Text Agent** — An AI agent for processing and mining biological text/literature references.
2. **Business Database** — A structured database for storing biological reference and mining results.

As code is added, update this file with build commands, test instructions, and module-level architecture notes.
