"""Shared test utilities"""

import warnings
import compiler

import lang as l
from typing import Dict, List
import machine as m


def listing(code):
    print("\n".join(f"{i} | {a}" for i, a in enumerate(code)))


def list_defs(defs):
    for n, c in defs.items():
        print(f"{n}:")
        listing(c)


def run_dbg_local(functions, data, *, trace=True):
    """Run the machine locally and print lots of state"""
    probe = m.DebugProbe(trace=trace)
    machine = m.LocalMachine(functions, data, "F_main", probe)
    if trace:
        machine.print_instructions()
    machine.run()
    print("*** FINISHED")
    machine.state.show()


def check_exec(defs: dict, data: m.LocalState, expected: m.LocalState):
    """Run a program to termination, and check that the data stack is as expected"""
    run_dbg_local(defs, data, trace=True)
    assert len(expected._ds) == len(data._ds)
    for i, (a, b) in enumerate(zip(expected._ds, data._ds)):
        assert i >= 0 and a == b


def check_compile_node(node, expected):
    """Check that the evaluation output is as expected"""
    result = [str(a) for a in compiler.compile_node(node).code]
    expected = [a.strip() for a in expected.split("\n")]
    expected = list(filter(lambda x: len(x), expected))  # Remove empty lines
    assert len(expected) == len(result)
    for i, (a, b) in enumerate(zip(result, expected)):
        assert i >= 0 and a.strip() == b.strip()


def check_compile_all(fn: l.Func, expected: Dict):
    """Check that some function definitions are correct"""
    defs = compiler.compile_all(fn)
    for k in defs.keys():
        if k not in expected:
            warnings.warn(f"Not checking definition of {k}")
    for k in expected.keys():
        assert k in defs
        assert len(defs[k]) == len(expected[k])
        for i, (a, b) in enumerate(zip(defs[k], expected[k])):
            # Awkward. Builtins take arguments in the source, but not in the
            # assembly. So this is to avoid having to instantiate real builtins
            # in EXPECTED
            if isinstance(a, l.Builtin):
                assert k and i >= 0 and type(a) == b
            else:
                assert k and i >= 0 and a == b