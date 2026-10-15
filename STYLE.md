# Pipecat Docs Style Guide

How pages on docs.pipecat.ai are written. It applies to everyone who edits
them, people and automation alike.

For anything this guide doesn't cover, follow the
[Google developer documentation style guide](https://developers.google.com/style).
Where the two differ, this guide wins. Frontmatter, navigation, and tooling
rules live in [CLAUDE.md](CLAUDE.md) and are not repeated here.

The examples marked **Good** come from pages the maintainers hold up as models.
The ones marked **Avoid** come from real edits that were later trimmed,
corrected, or closed.

## Readers

Two kinds of reader use these pages:

- **Developers** skim for the one thing they need, then leave.
- **Coding agents** read a page, or a fragment of it, with no surrounding
  context.

Both need the same thing: a complete, accurate statement of the current API,
with each fact stated once and placed where it would be looked for. Neither is
helped by history, rationale, or internals.

## Page Types

| Type      | Where                                          | Job                                                                                      | Length                    |
| --------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------- |
| Learn     | `pipecat/learn/`, `pipecat/fundamentals/`      | Explain a concept: the problem it solves, the options, how to choose.                    | As long as the idea needs |
| Guide     | `pipecat/`, `client/guides/`, `pipecat-cloud/` | Get one task done, in order.                                                             | Short; one task per page  |
| Reference | `api-reference/`                               | State the contract: every public parameter, type, default, constraint, error, and event. | Complete, and no more     |

Reference pages are exhaustive about public surface. Learn and guide pages are
selective: they show the common path and link to the reference for the rest.

A reference page opens by saying what the thing does, then links to the
concept page: "For a walkthrough, see [Pipecat Classifiers](/pipecat/learn/classifiers)."
A concept page ends by linking to the reference.

## What to Write

Document what a reader can **set, call, observe, or act on**:

- Parameters, settings, and their types and defaults
- Constraints: allowed values, limits, required combinations, dependency floors
- Errors: what raises, and when
- Events and their arguments
- Behavior a reader would otherwise get wrong ("The bot can be the active
  speaker while it talks.")
- How to migrate off something deprecated

Leave out:

- **The change itself.** No "now", "new", "previously", "no longer", or "as of
  this release". Pages describe the current API to someone who never saw the
  old one. History belongs in the changelog and in migration guides.
- **Rationale.** Why the code works this way is for maintainers. Docstrings,
  PR descriptions, and changelog entries are sources of facts, never of
  sentences.
- **Internals.** How a service talks to its provider, how a buffer is sized, or
  which task does the work. Exception: an internal detail the reader must
  account for in their own code.
- **Values the provider owns.** Language lists, model lists, provider-side
  defaults and ranges: link the provider's documentation. Our copy goes stale
  and theirs doesn't.
- **Test-only hooks** and parameters that exist for Pipecat's own test suite.
- **Alpha APIs**, until someone decides they are ready for a page.

If a change leaves nothing a reader can set, call, observe, or act on (an
internal refactor, a fix that restores documented behavior, a log message), it
needs no docs change.

**Avoid** (internals: nothing here changes what a user writes):

> Volume is measured over a rolling 400ms window, which provides stable
> readings that are less affected by brief dips between phonemes.

**Avoid** (maintainer rationale copied from a docstring):

> Flux's inline pronunciation markup is Early Access and is rejected with a
> fatal `DATA-0002` on any connection whose `speed` is not 1.0, so
> `pronunciation_transform_ipa()` speaks words as written.

**Good** (the same fact, for the reader):

> `pronunciation_transform_ipa()` has no effect on the Flux services: words are
> spoken as written.

## Say It Once

State each fact once per page, in the place a reader would look for it. A
parameter's default, effect, and constraints belong in its `ParamField` or
table row. Don't restate them in the overview, a feature list, a Note, and a
Usage comment as well.

Across pages, a one-sentence restatement with a link is fine. Repeating whole
sections or the same code sample on several pages is not. Reusing one example
_scenario_ across related pages is good: it makes them read as a set. Each
page's sample should still show what is specific to that page.

**Avoid**: one PR stated that a setting triggers a reconnect in the table row,
in a Notes bullet, and in a Usage comment. Another described pre-warming four
times across the overview, Features, How It Works, and Notes.

## Reference Pages

### Format

- Use `<ParamField>` for constructor arguments and CLI flags. Use tables for
  settings objects, result fields, properties, events, and method parameters.
  Follow whichever the page already uses.
- Types use Python syntax: `type="str | None"`,
  `type="Callable[[BackendOutput], Awaitable[BackendOutput]]"`.
- The **Default** column and `default=` attribute give Pipecat's default. When
  `None` means "not sent, so the provider's default applies", say so in the
  description. Don't put the provider's default in the Default column.
- Put the import path in its own code block before Configuration.
- Show method signatures in a bare `python` block under the method's heading,
  followed by one sentence that starts with what the method returns or does.

### Descriptions

Say what the parameter is, then what its default or `None` does, then any
constraint. Keep it to one or two sentences.

**Good**:

> Transcription mode: `"VERBATIM"` (the model default) or `"SMART"`, which
> removes disfluencies and applies light grammatical cleanup and formatting.
> Requires `google-genai >= 2.20.0`.

> OpenAI API key, when the classifier should have a client of its own. One of
> `api_key` and `client` is required.

State errors as their own sentence: "Raises `ClassifierError` when…".

### Deprecations

Mark the entry itself; don't add a separate Note elsewhere on the page. Use the
`deprecated` attribute and one italic line, with versions as `X.Y.Z`:

```mdx
<ParamField path="params" type="InputParams" default="None" deprecated>
  _Deprecated since 0.0.105._ Use `settings=DeepgramSTTService.Settings(...)`
  instead.
</ParamField>
```

Add the removal version ("_Deprecated since 1.10.0, removed in 2.0.0._") when
the source names one. In tables, start the description with the same italic
line. When a deprecated
API has no entry to mark but the page or section has a migration table, add a
row there. Keep deprecated entries short: the replacement, the version, nothing
else.

### Frames and Methods

Pipecat's public interface is frames. A frame pushed into the pipeline keeps
its place in order with the frames around it, such as the audio of the bot's
last sentence; a method call acts at once, out of that order. Some classes
also have methods, for work that has no place in the frame stream or that
crosses a boundary the pipeline doesn't, such as from the transport to the
call or the client.

- **When a frame does the job, document the frame** and use it in samples.
  Leave out a method that does the same thing, and replace it where a page
  already shows it.
- **Document a method when no frame does the same job**: session and
  connection control a reader calls from an event handler (capturing a
  participant, starting a recording, dialing out), lookups
  (`participants()`), and calls across the transport or client boundary.
- **Leave out methods meant for subclasses or for the framework itself**
  (`process_frame()`, `setup()`, `write_audio_frame()`). They belong on pages
  about extending Pipecat.

List the frames a reader pushes to a class, and the frames it pushes that a
reader acts on, in a `## Frames` section with a "Sent to" table and a "Pushed
by" table (Frame | Fields | Effect). Include the class's own frames and any
generic frame whose effect is specific to the class. Frames documented on the
frame reference pages need only a link.

### Service Pages

Use this section order. A section with nothing to say is left out.

1. `## Overview`: one sentence naming the class and what it does, then a
   `<CardGroup cols={2}>` linking the API reference, an example, and the
   provider's docs
2. `## Installation`: the `uv add` command
3. `## Prerequisites`: account, API key, and `### Required Environment Variables`
4. `## Configuration`: a `###` per class with its `<ParamField>`s, then
   `### Settings`, then a `###` per helper type
5. `## Usage`: a `###` per task, named for the task ("Restoring a
   Conversation", not "Advanced Usage")
6. `## Frames`, for frames a reader pushes to the class or acts on (see
   [Frames and Methods](#frames-and-methods))
7. `## Methods`, for public methods a reader calls that no frame replaces
8. `## Notes`: bullets with a bold label and a colon, for behavior that
   spans parameters ("**No local VAD**: The model detects the user's turns
   itself, so the pipeline needs no VAD analyzer.")
9. `## Event Handlers`: an Event | Description table, then one code block

A page documenting several classes may use a `##` per class, with Settings,
Usage, Frames, Methods, Notes, and Event Handlers as `###` under each.

Notes are not a second description of the parameters. If a bullet only
restates a `<ParamField>`, delete it.

## Changing Existing Pages

Size the edit to the change:

| Change                   | Edit                                                                      |
| ------------------------ | ------------------------------------------------------------------------- |
| New or changed parameter | One `<ParamField>` or table row. No Note, no example, no overview change. |
| New event                | One table row, plus a handler snippet if the page shows one per event.    |
| Changed default          | The default value, and the description only if it is now wrong.           |
| New class in a family    | Its page, plus every table, list, and count that names its siblings.      |
| Removed or renamed API   | Every page that mentions it, including examples and guides.               |

A table that grows by thirty lines for a one-row change is fine: that is
Prettier realigning columns, not new content.

- **Edit a line only if the change makes it false or incomplete.** Don't
  reword neighboring sentences; rewording is where errors get in.
- **Rewrite in place.** When the API's framing changes, change the sentence
  that frames it; don't add a paragraph that corrects it.
- **Delete what is stale.** A page that gets shorter is often the right
  result.
- **Check what the change makes wrong elsewhere.** An example, recipe,
  comparison table, or count on another page may now be false.
- **Re-read the whole page when you're done.** Check that every fact appears
  once, examples still run against the current API, and counts and lists
  match their tables.

## Callouts

Use a callout only for something a reader would otherwise get wrong. Most pages
need none. Never use one to draw attention to what a change happened to touch.

- `<Note>`: a side fact that affects usage ("`NOT_GIVEN` values are omitted
  from the API request entirely.")
- `<Tip>`: a recommendation ("Use `response` for the agent's reply unless you
  have a reason not to.")
- `<Warning>`: deprecation of a whole page or class, or a risk of data loss or
  cost

If the fact fits in the sentence already there, put it in the sentence.

## Code Samples

- Keep samples short, usually 5 to 25 lines. The first sample on a page has
  complete imports; later ones show only new imports and elide with `...`.
- Every sample must run against the current API. No deprecated parameters,
  no undefined names that the reader can't infer.
- Read API keys with `os.getenv("PROVIDER_API_KEY")`. Install with `uv add`.
- Use realistic data ("Hi, you've reached Dana. Leave a message.") and show
  results as trailing comments (`# 0.97`).
- Comments explain why, not what. Avoid `# Create the service`.
- Introduce a sample with a sentence ending in a colon.

## Prose

- Write short, declarative sentences in the present tense. Address the reader
  as "you".
- Join cause and effect with "so" rather than a new paragraph: "The model
  detects the user's turns itself, so the pipeline needs no VAD analyzer."
- Bold a term where it is defined, then gloss it: "a **state**, the thing the
  question is about".
- Name things exactly as the code does, in backticks: "`VoicemailDetector`
  makes that call", not "the voicemail detector makes that call".
- Use concrete numbers: "about a tenth of a second", not "very fast".
- Use colons, commas, and periods, not em dashes.
- Headings use Title Case and name a task or topic: "Create the Detector", not
  "Initialization".
- Don't open with "This page describes…". Start with what the thing does.
- No filler or marketing ("seamless", "powerful", "leverage", "it's worth
  noting"), and no feature lists that restate the reference.

**Good**:

> A greeting keeps going after its pauses, while a person stops and waits.

> The GPT-Live API takes conversation history only at session start.

> Every classifier answers or raises within a time bound of its own, so a
> caller waiting on one is never left hanging.

## Links

- Link the first mention of a class on a page to its reference page.
- Use in-page anchors for methods and sections: `[screen_tools()](#screen_tools)`.
  Anchors come from headings only; `<ParamField>` creates none.
- Link a provider's documentation instead of copying it.
