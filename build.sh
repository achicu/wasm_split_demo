set -ex

mkdir -p build

# Use -flto to create bitcode object files
emcc -o build/core_application.o core_application.cpp \
    -c -flto \
    -std=c++20 \
    -Wno-unknown-attributes \
    -Wno-c++2b-extensions \
    -pthread \
    --profiling-funcs

# Link the program
# Use --save-temps to dump a whole-program bitcode file we can analyze.
# Use --no-demangle to ensure the final binary that wasm-split will see has the
#   same function names as the bitcode we will analyze.
# Use -s SPLIT_MODULE to make the JS able to load a deferred module.
emcc -o build/index.html build/core_application.o \
    -flto -Wl,--save-temps,--no-demangle \
    --shell-file shell.html \
    -std=c++20 \
    -Wno-unknown-attributes \
    -Wno-c++2b-extensions \
    -pthread \
    -s ASSERTIONS=1 \
    -s NO_EXIT_RUNTIME=1 \
    -s 'EXPORTED_RUNTIME_METHODS=["ccall","cwrap"]' \
    -s PTHREAD_POOL_SIZE=2 \
    -s SPLIT_MODULE \
    --profiling-funcs

# Dump the call graph from the intermediate whole-program bitcode file
opt --print-callgraph build/index.wasm.0.5.precodegen.bc \
    2> build/callgraph.txt > /dev/null

# Analyze the call graph and determine which functions to split out
./analysis.py build/callgraph.txt -o build/secondary.txt \
    --strategy=only-editor-annotated

# Split the module
# Use --split-funcs to split out the listed functions.
# Use --placeholdermap -g to simplify debugging the split module.
wasm-split --all-features build/index.wasm.orig \
    -o1 build/index.wasm \
    -o2 build/index.deferred.wasm \
    --split-funcs=@build/secondary.txt \
    --placeholdermap -g

# Demangle the names in the placeholder map for convenience
llvm-cxxfilt < build/index.wasm.placeholders > build/placeholders.txt

node serve.js
