#!/usr/bin/python3

import argparse
import re
import subprocess
import sys


addr = '(:?0x[0-9a-f]*|None)'
RE_NULL_FUNC = re.compile(f"^Call graph node <<null function>><<{addr}>>" +
                          f"  #uses=[0-9]*$")
RE_NEW_FUNC = re.compile(f"^Call graph node for function: " +
                         f"'(?P<name>.*)'<<{addr}>>  #uses=[0-9]*$")
RE_CALL_FUNC = re.compile(f"^  CS<{addr}> calls function '(?P<name>.*)'$")
RE_CALL_INDIRECT = re.compile(f"^  CS<{addr}> calls external node$")


TAGS = ['_EDITOR_WASM_', '_MAIN_WASM_', '_RENDERER_WASM_']


class CallGraph:
    def __init__(self):
        # Set of all functions in the call graph
        self.functions = set()
        # Map each function to the set of functions it directly calls, if any
        self.callees = {}
        # Map each function to the set functions that directly call it, if any
        self.callers = {}
        # Set of functions that make indirect calls
        self.indirect_callers = set()
        # Set of functions that may be indirectly called
        self.indirect_callees = set()
        # Map each function to its demangled name
        self.demangled = {}
        # Map each tag to a set of functions with that tag.
        self.tags = {tag: set() for tag in TAGS}

    def add_function(self, func):
        assert func is not None
        if func in self.functions:
            return
        self.functions.add(func)
        self.callees[func] = set()
        self.callers[func] = set()

    # Record a call from `caller` to `callee`. If `caller` is None, then
    # `callee` may be indirectly called and if `callee` is None, then `caller`
    # makes an indirect call.
    def add_call(self, caller, callee):
        assert caller is not None or callee is not None
        if caller is None:
            self.indirect_callees.add(callee)
        elif callee is None:
            self.indirect_callers.add(caller)
        else:
            self.callees[caller].add(callee)
            self.callers[callee].add(caller)

    # Get the demangled names of all functions in the call graph. Use c++filt
    # -p to drop parameter and result types, which helps us ignore tags that
    # appear in those locations.
    def compute_demangled(self):
        funcs = list(self.functions)
        func_list = ''.join(f'{func}\n' for func in funcs)
        result = subprocess.run(
            ['c++filt', '-p'], text=True, input=func_list, capture_output=True)
        self.demangled = dict(zip(funcs, result.stdout.splitlines()))

    # Find the last tag in each symbol name so that e.g. tags on lambdas
    # override tags on enclosing functions, which in turn override tags on
    # enclosing classes, etc. TODO: Ignore tags for lambda operations other
    # than operator()?
    def compute_tags(self):
        for func in self.functions:
            # Remove tags in template and function parameters by demangling the
            # name and manually deleting contents within angle brackets and
            # parens. Remove operator names that may contain unrelated angle
            # brackets first.
            demangled = self.demangled[func]
            for op in ['->', '<', '>', '<=', '>=', '<=>']:
                demangled = demangled.replace(f'operator{op}', '')
            stripped = []
            depth = 0
            for c in demangled:
                if depth == 0:
                    stripped.append(c)
                if c in ('<', '('):
                    depth += 1
                if c in ('>', ')'):
                    depth -= 1
                if depth < 0:
                    print('error: negative bracket depth!')
                    print(f'{func}\n{demangled}')
                    sys.exit(1)
            stripped = ''.join(stripped)
            tag_indices = [stripped.rfind(tag) for tag in TAGS]
            last_tag_index = max(tag_indices)
            if last_tag_index != -1:
                tag = TAGS[tag_indices.index(last_tag_index)]
                self.tags[tag].add(func)


def parse_call_graph(cg_file):
    try:
        with open(cg_file, "rt") as f:
            callgraph = CallGraph()
            caller = None
            for line in f:
                if not line or line.isspace():
                    continue
                null_func = RE_NULL_FUNC.match(line)
                new_func = RE_NEW_FUNC.match(line)
                call_func = RE_CALL_FUNC.match(line)
                call_indirect = RE_CALL_INDIRECT.match(line)
                if null_func:
                    caller = None
                elif new_func:
                    caller = new_func.group('name')
                    callgraph.add_function(caller)
                elif call_func:
                    callee = call_func.group('name')
                    callgraph.add_function(callee)
                    callgraph.add_call(caller, callee)
                elif call_indirect:
                    callgraph.add_call(caller, None)
                else:
                    print(f'WARNING: unrecognized input line: {line}')
        callgraph.compute_demangled()
        callgraph.compute_tags()
        return callgraph
    except OSError:
        print(f'could not open {cg_file}')
        sys.exit(1)


def print_functions(callgraph):
    print(f'{len(callgraph.functions)} functions:')
    for func in sorted(callgraph.functions):
        print(callgraph.demangled[func])
    return []


def print_callgraph(callgraph):
    print(f'{len(callgraph.functions)} functions')
    print()
    for func in sorted(callgraph.functions):
        tag = None
        for t, tagged in callgraph.tags.items():
            if func in tagged:
                tag = t
        print(func)
        print(f'    Address taken: {func in callgraph.indirect_callees}')
        print(f'    Calls indirectly: {func in callgraph.indirect_callers}')
        print(f'    Tag: {tag}')
        print(f'    Callees ({len(callgraph.callees[func])}):')
        for callee in sorted(callgraph.callees[func]):
            print(f'        {callee}')
        print(f'    Callers ({len(callgraph.callers[func])}):')
        for caller in sorted(callgraph.callers[func]):
            print(f'        {caller}')
        print()
    return []


def print_tagged(callgraph):
    for tag in TAGS:
        print(f'{tag} ({len(callgraph.tags[tag])}):')
        for func in sorted(callgraph.tags[tag]):
            print(f'    {callgraph.demangled[func]}')
        print()
    return []


# Split out only functions explicitly tagged with _EDITOR_WASM_
def only_editor_annotated(callgraph):
    result = [func for func in sorted(callgraph.functions)
              if func in callgraph.tags['_EDITOR_WASM_']]
    print(len(result))
    return result


# For each splitting strategy, map the strategy name to a function implementing
# it. The functions should take a CallGraph argument and return a list of
# functions to be split out into the secondary module.
STRATEGIES = {
    'only-editor-annotated': only_editor_annotated,

    # These print useful debugging information rather than performing a split
    'print-functions': print_functions,
    'print-callgraph': print_callgraph,
    'print-tagged': print_tagged,
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', choices=STRATEGIES.keys(),
                        default='print-callgraph')
    parser.add_argument('-o', dest='output', default='-',
                        help='file to which the secondary functions '
                             'will be written')
    parser.add_argument('callgraph',
                        help='The result of `opt --print-callgraph`')
    return parser.parse_args()


def write_output(output, funcs):
    def do_write(f):
        for func in funcs:
            print(func, file=f)
    if output == '-':
        do_write(sys.stdout)
    else:
        try:
            with open(output, 'w') as f:
                do_write(f)
        except OSError:
            print(f'could not open {output}')


def main():
    args = parse_args()
    callgraph = parse_call_graph(args.callgraph)
    secondary_funcs = STRATEGIES[args.strategy](callgraph)
    if secondary_funcs:
        write_output(args.output, secondary_funcs)
    else:
        print('warning: not splitting any functions')


if __name__ == '__main__':
    main()
