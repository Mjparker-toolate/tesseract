# Project subagents

Custom Cursor subagents for the Tesseract OCR codebase. Each runs in its own isolated context with the
system prompt defined in its `.md` file, so the main conversation stays uncluttered.

These are project-scoped (`.cursor/agents/`) and checked into version control, so everyone working in this
repository gets them automatically. Personal agents can live in `~/.cursor/agents/`; when names collide,
the project-level definition here wins.

## Roster

| Agent | Use it for |
| --- | --- |
| `build-tester` | Configure/build/install `libtesseract`, the `tesseract` CLI, and the training tools, then verify OCR end to end. |
| `code-reviewer` | C++17 review focused on Leptonica memory safety, undefined behavior, and project conventions. |
| `debugger` | Root-cause analysis for crashes, wrong OCR output, and build failures, using runtime evidence. |
| `test-runner` | OCR smoke checks and the googletest unit suite, including the large external test corpus. |
| `fuzz-tester` | The `unittest/fuzzers` libFuzzer harness, run before CIFuzz sees the pull request. |
| `training-specialist` | The LSTM/legacy training pipeline (`text2image`, `lstmtraining`, `lstmeval`, `combine_tessdata`). |

Typical flow: `code-reviewer` on the diff, `build-tester` to prove it compiles and still recognizes text,
`test-runner` for the suite, `debugger` when something breaks, and `fuzz-tester` when the change touches
image decoding or parsing.

## Conventions these agents rely on

- **Pin the compiler.** The default `c++` alternative resolves to Clang, which targets a newer GCC than the
  installed `libstdc++` dev package, so an unpinned `cmake ..` fails with `cannot find -lstdc++`. Always pass
  `-DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++`. (`fuzz-tester` is the exception: libFuzzer needs Clang.)
- **Use a login shell.** Run verification commands via `bash -lc '...'` so `/etc/profile.d/tesseract.sh`
  exports `TESSDATA_PREFIX=/usr/local/share/tessdata`; without it `tesseract` looks in `./` and fails to
  load `eng`.
- **All executables install by default.** `BUILD_TRAINING_TOOLS` is `ON`, so `cmake --install` places the
  `tesseract` CLI plus all 15 training tools in `/usr/local/bin`.
- **Submodules matter.** `git submodule update --init --recursive` provides both the `test` data repo and
  googletest. Without googletest the `BUILD_TESTS` block is skipped silently.

## Editing or adding an agent

Each file needs YAML frontmatter with a lowercase, hyphenated `name` and a specific `description` — the
description is what the model matches on when deciding whether to delegate, so include concrete trigger
terms and "use proactively" where automatic delegation is wanted. The markdown body becomes the system
prompt: state the workflow, the exact commands, the output format, and the constraints.
