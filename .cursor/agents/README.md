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
| `test-runner` | The googletest unit suite only, including the >1 GB external test corpus. |
| `fuzz-tester` | The `unittest/fuzzers` libFuzzer harness, run before CIFuzz sees the pull request. |
| `training-specialist` | The LSTM/legacy training pipeline (`text2image`, `lstmtraining`, `lstmeval`, `combine_tessdata`). |

Typical flow: `code-reviewer` on the diff, `build-tester` to prove it compiles and still recognizes text
(it owns the quick OCR smoke checks), `test-runner` when the full suite is warranted, `debugger` when
something breaks, and `fuzz-tester` when the change is on the recognition path reachable from
`TessBaseAPI`. Note the fuzz harness synthesizes its own bitmap rather than decoding image files, so
image-decoder changes are *not* what it exercises.

## Relationship to `.github/copilot-instructions.md`

[`.github/copilot-instructions.md`](../../.github/copilot-instructions.md) is this repository's canonical,
upstream-maintained agent guidance, and it closes with "Trust these instructions." Treat it as the source of
truth. These agents exist to add what it does not cover (fuzzing, the training pipeline, failure triage) and
to record traps found by actually running the commands here.

Where an agent departs from it, the departure is deliberate:

| Canonical says | These agents do | Why |
| --- | --- | --- |
| `mkdir build && cd build && cmake ..` | `cmake -S . -B build -G Ninja` | Equivalent out-of-source build in one command; Ninja matches `cmake.yml` CI. |
| Plain `cmake ..` (no compiler named) | Pin `-DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++` | The default `c++` is Clang here and can fail to link `-lstdc++`; pinning is deterministic. |
| OpenMP "enabled by default if available" | `-DOPENMP_BUILD=OFF` | Matches the `cmake.yml` and `autotools.yml` CI matrices. |
| "With CMake: … `ctest`" | Prefer autotools `make check` | CI never sets `BUILD_TESTS` or runs `ctest`; the CMake path also has a false-green failure mode (see `test-runner`). |
| Pinned `gcc/g++` everywhere | `fuzz-tester` uses Clang | libFuzzer requires Clang. |

Genuinely aligned (do not "fix" these): traineddata comes from the `tesseract-ocr/tessdata` repository, which
is what the canonical file specifies and what keeps the legacy engine (`--oem 0`) working.

## Conventions these agents rely on

- **Pin the compiler.** The default `c++` alternative resolves to Clang, which selects the highest-numbered
  GCC tree it finds. If the matching `libstdc++-<N>-dev` is absent, an unpinned `cmake ..` fails — either
  `cannot find -lstdc++` at link time or `'cstring' file not found` at compile time. Always pass
  `-DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++`. (`fuzz-tester` is the exception: libFuzzer needs Clang.)
- **Both OCR engines must keep working.** The installed `eng.traineddata` carries legacy components, so
  `--oem 0` and `--oem 1` both run and both match `test/testing/phototest.txt` exactly. Swapping in
  `tessdata_fast`/`tessdata_best` models silently breaks `--oem 0`.
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
