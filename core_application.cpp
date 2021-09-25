// Copyright 2021 Adobe
// All Rights Reserved.
//
// NOTICE: Adobe permits you to use, modify, and distribute this file in accordance with the terms
// of the Adobe license agreement accompanying it.

#include <emscripten.h>
#include <condition_variable>
#include <deque>
#include <functional>
#include <iostream>
#include <mutex>
#include <thread>

using namespace std;

// For things that are known to only be required on main.wasm, but they are not part of the callgraph of the main thread.
#define MAIN_WASM     [[gnu::abi_tag("_MAIN_WASM_")]]

// The symbol is only needed by the renderer thread.
#define RENDERER_WASM [[gnu::abi_tag("_RENDERER_WASM_")]]

// The symbol is only needed by the renderer thread for editing purposes, expected to be loaded on-demand via wasm-split.
#define EDITOR_WASM   [[gnu::abi_tag("_EDITOR_WASM_")]]

class core_application;

using core_application_ptr = intptr_t;

core_application* to_cpp(core_application_ptr app) {
    return reinterpret_cast<core_application*>(app);
}

core_application_ptr to_js(core_application* app) {
    return reinterpret_cast<core_application_ptr>(app);
}


class core_application {
    // BG task queue
    mutex _mutex;
    condition_variable _condition;
    bool _done{false};
    deque<function<void()>> _bgTasks;
    thread _thread{[&] {
        for (auto task = dequeueBg(); task; task = dequeueBg()) {
            task();
        }
    }};

    auto dequeueBg() -> function<void()> {
        unique_lock lock{_mutex};
        _condition.wait(lock, [&] { return !_bgTasks.empty() || _done; });
        if (_bgTasks.empty()) return {};
        auto result{_bgTasks.front()};
        _bgTasks.pop_front();
        return result;
    }

    // Main queue
    mutex _mainMutex;
    deque<function<void()>> _mainTasks;
    bool _scheduledToRunOnMain = false;

    auto dequeueMain() -> function<void()> {
        unique_lock lock{_mainMutex};
        if (_mainTasks.empty()) {
            // Make sure that future calls to main will schedule another main thread request.
            _scheduledToRunOnMain = false;
            return {};
        }
        auto result{_mainTasks.front()};
        _mainTasks.pop_front();
        return result;
    }

 public:
    ~core_application() {
        {
        unique_lock lock{_mutex};
        _done = true;
        }
        _condition.notify_one();
        _thread.join();
    }

    template <class F>
    void runOnBgThread(F&& f) {
        {
            unique_lock lock{_mutex};
            _bgTasks.emplace_back(forward<F>(f));
        }
        _condition.notify_one();
    }

    template <class F>
    void runOnMain(F&& f) {
        {
            unique_lock lock{_mainMutex};
            _mainTasks.emplace_back(forward<F>(f));
            if (_scheduledToRunOnMain) {
                // We already have a pending main executor.
                return;
            }

            // Schedule to run on the main thread.
            _scheduledToRunOnMain = true;
        }
        MAIN_THREAD_ASYNC_EM_ASM({
            Module.ccall('runMainTasks', null, ['number'], [ $0 ]);
        }, to_js(this));
    }

    void runMainTasks() {
        for (auto task = dequeueMain(); task; task = dequeueMain()) {
            task();
        }
    }

    void runTask3() {
        cout << "Running task3.\n";
    }
};

void runTask2() {
    cout << "Running task2.\n";
}

class ObjectWithVTable {
 public:
    virtual void runTask4() {
        cout << "Running task4 - base object.\n";
    }
};

class RENDERER_WASM ImplObjectWithVTable: public ObjectWithVTable {
 private:
    virtual void runTask4() {
        cout << "Running task4 - subclass object.\n";
    }
};

#ifdef __cplusplus
extern "C" {
#endif


EMSCRIPTEN_KEEPALIVE core_application_ptr createApp() {
    cout << "Creating app.\n";
    return to_js(new core_application());
}

EMSCRIPTEN_KEEPALIVE void runTask1(core_application_ptr app) {
    auto application = to_cpp(app);
    application->runOnBgThread([] RENDERER_WASM { cout << "Running Task 1.\n"; });
}

EMSCRIPTEN_KEEPALIVE void runTask2(core_application_ptr app) {
    auto application = to_cpp(app);
    application->runOnBgThread([] RENDERER_WASM {
        // Global method.
        runTask2();
    });
}

EMSCRIPTEN_KEEPALIVE void runTask3(core_application_ptr app) {
    auto application = to_cpp(app);
    application->runOnBgThread([ application ] RENDERER_WASM {
        // Method on the application.
        application->runTask3();
    });
}

EMSCRIPTEN_KEEPALIVE void runTask4(core_application_ptr app) {
    auto application = to_cpp(app);

    std::shared_ptr<ObjectWithVTable> ptr =
        std::make_shared<ImplObjectWithVTable>();
    application->runOnBgThread([ ptr ] EDITOR_WASM {
        ptr->runTask4();
    });
}

EMSCRIPTEN_KEEPALIVE void runTask5(core_application_ptr app) {
    auto application = to_cpp(app);

    application->runOnBgThread([ application ] EDITOR_WASM {
        cout << "Running Task 5 in bg thread.\n";

        application->runOnMain([ application ] MAIN_WASM {
            cout << "Running Task 5 in main 1.\n";

            application->runOnBgThread([ application ] EDITOR_WASM {
                cout << "Running Task 5 in bg thread again.\n";

                application->runOnMain([ ] MAIN_WASM {
                    cout << "Running Task 5 in main thread again.\n";
                });
            });
        });
    });
}

EMSCRIPTEN_KEEPALIVE void runMainTasks(core_application_ptr app) {
    auto application = to_cpp(app);
    application->runMainTasks();
}


#ifdef __cplusplus
}
#endif

