# Pipecat Documentation Codebase Instructions

This is the official documentation repository for [Pipecat](https://github.com/pipecat-ai/pipecat), an open-source Python framework for building voice and multimodal AI agents. The docs are deployed at [docs.pipecat.ai](https://docs.pipecat.ai).

## Tech Stack & Structure

- **Platform**: [Mintlify](https://mintlify.com/) documentation framework
- **Config file**: `docs.json` - defines navigation, theme, and site structure
- **Content format**: MDX files (Markdown with JSX components)

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `getting-started/` | Onboarding and quickstart guides |
| `guides/` | Learning tutorials, features, telephony integrations |
| `server/` | Python server API reference (services, utilities, pipeline) |
| `client/` | Client SDK docs (JS, React, iOS, Android, C++) |
| `deployment/` | Deployment guides for Pipecat Cloud and other platforms |
| `cli/` | Pipecat CLI reference |

## MDX File Conventions

Every MDX file requires YAML frontmatter:

```mdx
---
title: "Page Title"
description: "Brief description for SEO and navigation"
---
```

### Mintlify Components

Use Mintlify's built-in components (see [component docs](https://mintlify.com/docs/content/components/)):

```mdx
<Card title="Title" icon="icon-name" href="/path">Description</Card>
<CardGroup cols={2}>...</CardGroup>
<Note>Important information</Note>
<Warning>Critical warnings</Warning>
<Frame><img src="./images/example.png" /></Frame>
<CodeGroup>...</CodeGroup>
```

### Code Examples Pattern

Service documentation follows a consistent structure (see [server/services/llm/openai.mdx](server/services/llm/openai.mdx)):

1. Overview with `<CardGroup>` linking to API reference, examples, and external docs
2. Installation section with pip command
3. Prerequisites (account setup, environment variables)
4. Usage examples with Python code blocks

## Navigation Structure

Navigation is defined in `docs.json` under `navigation.tabs[].groups[].pages`. When adding new pages:

1. Create the MDX file in the appropriate directory
2. Add the path (without `.mdx` extension) to `docs.json`
3. Follow existing naming: lowercase, hyphenated (e.g., `function-calling.mdx`)

## Local Development

```bash
npm i -g mint    # Install Mintlify CLI
mint dev         # Start local server at localhost:3000
mint update      # Update Mintlify if issues occur
```

## Deployment

- **Production**: Automatically deployed when merged to `main`
- **Previews**: PR preview deploys are created automatically when PRs are opened on GitHub

## Writing Style

Write as clearly as possible using simple words. Avoid jargon when a plain term works. Prefer short sentences and active voice.

## Content Patterns

### Service Documentation

Services are organized by category in `server/services/`:
- `stt/` - Speech-to-text (Deepgram, Whisper, etc.)
- `tts/` - Text-to-speech (Cartesia, ElevenLabs, etc.)
- `llm/` - Language models (OpenAI, Anthropic, etc.)
- `s2s/` - Speech-to-speech
- `transport/` - WebRTC/WebSocket transports

### Linking to Examples

Reference the main Pipecat repos for code examples:
- Framework examples: `https://github.com/pipecat-ai/pipecat/blob/main/examples/`
- Full applications: `https://github.com/pipecat-ai/pipecat-examples/`

### Images

Store images in local `images/` directories relative to the content, or in the root `/images/` folder for shared assets.

## Key Concepts to Understand

- **Pipeline**: Core architecture connecting frame processors for real-time audio/video
- **Frames**: Data containers (audio, text, images, control signals) flowing through pipelines
- **Frame Processors**: Modular workers that process specific frame types (STT, LLM, TTS)
- **Transports**: Handle real-time communication (Daily WebRTC, WebSockets, telephony)
- **RTVI**: Real-Time Voice and Video Inference standard implemented by all client SDKs
