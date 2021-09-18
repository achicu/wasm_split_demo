mkdir -p build
emcc -o build/index.html core_application.cpp \
    --shell-file shell.html \
    -std=c++20 \
    -Wno-unknown-attributes \
    -Wno-c++2b-extensions \
    -pthread \
    -s WASM=1 \
    -s ASSERTIONS=1 \
    -s NO_EXIT_RUNTIME=1 \
    -s 'EXPORTED_RUNTIME_METHODS=["ccall","cwrap"]' \
    -s PTHREAD_POOL_SIZE=2
node serve.js
