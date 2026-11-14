# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Tesseract OCR: `libtesseract` (C++ library with C wrapper) plus the `tesseract` CLI and training tools. Version is in `VERSION`.

`.github/copilot-instructions.md` is the upstream-maintained agent guide (dependencies, common build failures, CI overview). `.cursor/agents/*.md` record traps found by actually running builds, tests and the fuzzer here; read the relevant one before doing that kind of work. This file summarizes both and corrects them where they disagree with the source.

## Build

Two build systems are maintained in parallel and both run in CI. **Adding, removing or renaming a source file means editing both**: `Makefile.am` (`libtesseract_la_SOURCES`, `check_PROGRAMS`) and `cmake/SourceLists.cmake` (`TESSERACT_SRC_CORE`, or `TESSERACT_SRC_LEGACY` for legacy-engine-only files) / `unittest/CMakeLists.txt`. `sw.cpp` globs `src/` and needs no change.

CMake (out-of-source only; in-source builds are rejected):
```bash
git submodule update --init --recursive   # googletest + test data (test/)
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DOPENMP_BUILD=OFF \
  -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++
cmake --build build
```
Always pin `gcc`/`g++`: the default `c++` here can be Clang picking a GCC tree with no matching `libstdc++-dev`, failing with `cannot find -lstdc++` or `'cstring' file not found`. Useful options: `BUILD_TRAINING_TOOLS` (ON), `BUILD_TESTS` (OFF), `DISABLED_LEGACY_ENGINE`, `GRAPHICS_DISABLED`, `DISABLE_TIFF/ARCHIVE/CURL`, `ENABLE_NATIVE`. CMake compiles as C++20 when the compiler supports it, otherwise C++17; code must still build as C++17.

Autotools (what CI uses for the unit tests):
```bash
./autogen.sh && ./configure && make -j && make training
./configure 'CXXFLAGS=-g -O2 -fsanitize=address,undefined'   # sanitizer build, as in CI
```

Required: Leptonica (`libleptonica-dev`). Training tools additionally need pango, cairo, ICU.

## Tests

googletest unit tests live in `unittest/*_test.cc`, one executable per file.

- Full suite: `make check` (results in `test-suite.log`). It needs a >1 GB corpus cloned from `egorpugin/tessdata` (see `.github/workflows/unittest.yml`); autotools expects `tessdata`, `tessdata_best`, `tessdata_fast`, `langdata_lstm` in the **parent** of the repo directory (`Makefile.am` `TESSDATA_DIR`), while the CMake tests look in `<repo>/tessdata`. Only download it when the task warrants.
- Single test (autotools): `make check TESTS=stats_test`, or run `./stats_test --gtest_filter='StatsTest.*'` after building it with `make stats_test`.
- Single test (CMake, `-DBUILD_TESTS=ON`): `cmake --build build --target stats_test && ctest --test-dir build -R stats_test --output-on-failure`.
- CMake false-green trap: without the googletest submodule, zero tests are registered and `ctest` exits 0. Confirm `-- Enabled tests:` appears in configure output and `ctest -N` reports a nonzero count.

Quick OCR smoke check (needs `eng` traineddata from `tesseract-ocr/tessdata`, the combined models, and `TESSDATA_PREFIX` set). Check both engines, since they are separate code paths:
```bash
tesseract test/testing/phototest.tif /tmp/p1 --oem 1 && diff /tmp/p1.txt test/testing/phototest.txt
tesseract test/testing/phototest.tif /tmp/p0 --oem 0 && diff /tmp/p0.txt test/testing/phototest.txt
```
`--oem 0` failing with "components are not present" means `tessdata_fast`/`tessdata_best` models are installed, not a code bug. Don't use `eurotext.tif` as an eng check; its ground truth is multilingual.

Fuzzing: `unittest/fuzzers/fuzzer-api.cpp` (libFuzzer, Clang only). It synthesizes a 100x100 1-bpp image from the first 1250 input bytes, so it covers layout and recognition, not image decoding. See `.cursor/agents/fuzz-tester.md` for the build line. CIFuzz runs on PRs to `main` touching `*.cpp`/`*.h`.

## Architecture

Request flow through the library:

1. **`TessBaseAPI`** (`include/tesseract/baseapi.h`, `src/api/baseapi.cpp`) is the public entry point; `capi.cpp` wraps it for C. `src/tesseract.cpp` is the CLI on top of it.
2. **`Tesseract`** (`src/ccmain/tesseractclass.{h,cpp}`) owns the per-language engine state and most tunables. One instance per loaded language (sub-languages via `-l eng+deu` become extra instances).
3. **Thresholding** (`ccmain/thresholder.cpp`) binarizes the Leptonica `Pix`.
4. **Page layout** (`ccmain/pagesegmain.cpp` → `src/textord/`): column finding, tab vectors, tables, text lines, word segmentation. Produces a `BLOCK`/`ROW`/`WERD` hierarchy (`src/ccstruct/`).
5. **Recognition** (`ccmain/control.cpp`, `recog_all_words`), split by OCR engine mode:
   - LSTM (`--oem 1`): `ccmain/linerec.cpp` → `src/lstm/` (`LSTMRecognizer`, network layers, `RecodeBeamSearch`). Matrix kernels are in `src/arch/`, picked at runtime by `simddetect.cpp` (SSE/AVX/AVX2/AVX512/FMA/NEON/RVV).
   - Legacy (`--oem 0`): `src/wordrec/` (segmentation search) + `src/classify/` (adaptive/static shape classifier) + `src/dict/` (dawgs, permuter).
6. **Results** go out through `PageIterator`/`ResultIterator` (`ccmain/*iterator.cpp`) and the renderers in `src/api/*renderer.cpp` (text, hOCR, ALTO, PAGE, PDF, TSV, box formats).

Cross-cutting conventions:
- **Legacy engine guard**: legacy-only code is wrapped in `#ifndef DISABLED_LEGACY_ENGINE` across `src/` and its files are listed separately in CMake (`TESSERACT_SRC_LEGACY`) and in a conditional block in `Makefile.am`. Changes touching shared code must keep the `-DDISABLED_LEGACY_ENGINE=ON` build compiling.
- **`GRAPHICS_DISABLED`** removes the ScrollView debug viewer (`src/viewer/`, Java client in `java/`).
- **Parameters** (`src/ccutil/params.h`): tunables are declared with `INT_VAR_H`/`BOOL_VAR_H`/`STRING_VAR_H`/`double_VAR_H` in headers and defined with the matching `*_MEMBER` macros in constructors. They are settable via `-c name=value`, config files under `tessdata/configs/`, or `SetVariable`; list them with `tesseract --print-parameters`.
- **traineddata** is a container of components (LSTM model, unicharset, dawgs, legacy classifier) read by `TessdataManager` (`ccutil/tessdatamanager.cpp`). Which components exist decides which engine modes work.
- **Training** (`src/training/`): `common/` and `unicharset/` are shared libraries; `pango/` (text rendering for `text2image`) is optional. CLI tools include `lstmtraining`, `lstmeval`, `combine_tessdata`, `text2image`.
- Image I/O and memory: everything uses Leptonica `Pix`. Pair `pixDestroy` with every owned `Pix`; strings returned by the API (e.g. `GetUTF8Text`) are freed with `delete[]`. Inputs are attacker-controlled images, so bounds and overflow checks on pixel math matter.

## Style

- `clang-format` with the repo's `.clang-format`, which is **Google-based** (Copilot instructions say LLVM; the file wins). Don't reformat code unrelated to the change.
- Classes and functions are `CamelCase`; variables and parameters are `snake_case`.
