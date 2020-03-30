"""AWS (lambda / ECS) runtime

In AWS, there will be one Machine executing in the current context, and others
executing elsewhere, as part of the same "session". There is one Controller per
session.

There's a queue of "runnable machines".

Run machine: push the new machine onto the queue.
- At a fork
- When a future resolves

Stop: pop something from the queue and Start it

Start top level: make a new machine and run it
Start existing (fork or cont): take an existing stopped machine and run it


A session is created when a handler is first called. Multiple machines
(threads) may exist in the session.

Data per session:
- futures (resolved, value, chain, continuations - machine, offset)
- machines (probe logs, state - ip, stopped flag, stacks, and bindings)

We could lock it to a single object:
- session (controller info, futures, machines)

Data exchange points:
- machine forks (State of new machine set to point at the fork IP)
- machine waits on future (continuation added to that future)
- machine checks whether future is resolved
- future resolves (must refresh list of continuations)
- top level machine finishes (Controller sets session result)
- machine stops (upload the State)
- machine continues (download the State)


# NOTE - some handlers cannot terminate early, because they have to maintain a
# connection to a client. This is a "hardware" restriction. So if an HTTP
# handler calls something async, it has to wait for it. Anything /that/ function
# calls can be properly async. But the top level has to stay alive. That isn't
# true of all kinds of Handlers!!
#
# ONLY THE ONES THAT HAVE TO SEND A RESULT BACK
#
# So actually that gets abstracted into some kind of controller interface - the
# top level "run" function. For HTTP handlers, it has to block until the
# Controller finishes. For others, it can just return. No Controller logic
# changes necessary. Just the entrypoint / wrapper.
"""

import json
import time
import uuid
import traceback
import warnings
from functools import wraps
from typing import List, Tuple

import boto3

from .. import compiler
from ..machine import C9Machine, ChainedFuture, Controller, Probe
from ..state import State
from . import aws_db as db
from .aws_db import ContinuationMap, FutureMap, MachineMap
from ..lambda_utils import get_lambda_client


class AwsProbe(Probe):
    def __init__(self, m: MachineMap):
        self.m = m
        self._logs = []
        self._step = 0

    def log(self, msg):
        self._logs.append(f"*** <{self.m.machine_id}> {msg}")

    def on_step(self, m: C9Machine):
        self._step += 1
        self.log(f"[step={self._step}, ip={m.state.ip}] {m.instruction}")

    def on_stopped(self, m: C9Machine):
        self._step += 1
        self.log(f"[step={self._step}] :: stopped")

    @property
    def logs(self):
        return list(self._logs)


class AwsFuture(ChainedFuture):
    def __init__(self, session, future_id, lock):
        # ALL access to this future must be wrapped in a db lock/update, as we
        # access _data directly here. The user is responsible for this.
        self.lock = lock
        self._session = session
        self._future_id = future_id

    def __repr__(self):
        return f"<Future {self._future_id}>"

    @property
    def _data(self):
        # We can't assign data once at __init__ because the underlying pointer
        # changes
        return db.get_future(self._session, self._future_id)

    @property
    def resolved(self) -> bool:
        return self._data.resolved

    @resolved.setter
    def resolved(self, value):
        self._data.resolved = value

    @property
    def value(self):
        return self._data.value

    @value.setter
    def value(self, value):
        self._data.value = value

    @property
    def chain(self) -> ChainedFuture:
        # All futures share the same lock (could optimise later)
        return AwsFuture(self._session, self._data.chain, self.lock)

    @chain.setter
    def chain(self, other: ChainedFuture):
        self._data.chain = other._future_id

    @property
    def continuations(self):
        return [(c.machine_id, c.offset) for c in self._data.continuations]

    def add_continuation(self, machine_id, offset):
        c = ContinuationMap(machine_id=machine_id, offset=offset)
        self._data.continuations.append(c)


def with_self_lock(inst_method):
    """Wrap an instance method with self.lock"""

    @wraps(inst_method)
    def _wrapper(self, *args, **kwargs):
        with self.lock:
            return inst_method(self, *args, **kwargs)

    return _wrapper


class AwsController(Controller):
    def __init__(self, executable_name, executable, session, do_probe=False):
        super().__init__()
        self.executable_name = executable_name
        self.executable = executable
        self._session = session
        self.lock = db.SessionLocker(session)
        self.do_probe = do_probe
        self.this_machine_is_top_level = False
        # These can be immediate values as they're only relevant for the current
        # context
        self.result = None

    def finish(self, result):
        self.result = result
        with self.lock:
            self._session.finished = True
            self._session.result = result

    @property
    def finished(self):
        self._session.refresh()
        return self._session.finished

    def stop(self, m: C9Machine):
        assert m is self.this_machine
        with self.lock:
            m_id = self.this_machine_id
            self._session.machines[m_id].state = self.this_machine_state
            self._session.machines[m_id].probe_logs = self.this_machine_probe.logs

    def is_top_level(self, m: C9Machine):
        # Is the currently executing machine the top level?
        assert m is self.this_machine
        return self.this_machine_is_top_level

    def get_state(self, m: C9Machine) -> State:
        assert m is self.this_machine
        return self.this_machine_state

    def get_probe(self, m: C9Machine) -> AwsProbe:
        assert m is self.this_machine
        return self.this_machine_probe

    def probe_log(self, m: C9Machine, message: str):
        assert m is self.this_machine
        self.this_machine_probe.log(f"[CTRL] {message}")

    def get_result_future(self, m: C9Machine) -> AwsFuture:
        # Only one C9Machine is ever running in a controller in AWS at a time,
        # so if m is a C9Machine, it must be this_machine.
        # self._session.
        if isinstance(m, C9Machine):
            assert m is self.this_machine
            return self.this_machine_future
        else:
            assert isinstance(m, MachineMap)
            return AwsFuture(self._session, m.future_fk, self.lock)

    def is_future(self, f):
        return isinstance(f, AwsFuture)

    @with_self_lock
    def get_or_wait(self, m: C9Machine, future: AwsFuture, offset: int):
        # prevent race between resolution and adding the continuation
        assert m is self.this_machine
        resolved = future.resolved
        if resolved:
            value = future.value
        else:
            future.add_continuation(self.this_machine_id, offset)
            value = None
        return resolved, value

    # No need to lock - chain_resolve will do it
    def set_machine_result(self, m: C9Machine, value):
        assert m is self.this_machine
        chain_resolve(
            self.this_machine_future, value, self.run_waiting_machine,
        )

    ## After this point, only deal with MachineMap

    def new_machine(self, args: list, top_level=False) -> MachineMap:
        # Called by machine and self
        with self.lock:
            m = db.new_machine(self._session, args, top_level=top_level)
        return m

    def run_forked_machine(self, m: MachineMap, new_ip: int):
        assert isinstance(m, MachineMap)
        with self.lock:
            self._session.machines[m.machine_id].state.ip = new_ip
        self._run_machine_async(m.machine_id)

    def run_waiting_machine(self, machine_id: int, offset: int, value):
        # This is called from chain_resolve. See self.get_or_wait - the
        # continuation holds machine_id
        with self.lock:
            self._session.machines[machine_id].state.ds_set(offset, value)
            self._session.machines[machine_id].state.stopped = False
        self._run_machine_async(machine_id)

    def _run_machine_async(self, m):
        assert isinstance(m, int)
        self.this_machine_probe.log(f"Starting new machine asynchronously - {m}")
        client = get_lambda_client()
        payload = dict(
            executable_name=self.executable_name,
            session_id=self._session.session_id,
            machine_id=m,
        )
        res = client.invoke(
            # --
            FunctionName="c9run",
            InvocationType="Event",
            Payload=json.dumps(payload),
        )
        if res["StatusCode"] != 202 or "FunctionError" in res:
            err = res["Payload"].read()
            raise Exception(f"Invoke lambda failed {err}")

    def run_machine(self, m: MachineMap):
        # m must be full initialised (latest data from DB)
        self.this_machine_id = m.machine_id
        self.this_machine_state = m.state
        self.this_machine_probe = AwsProbe(m) if self.do_probe else Probe()
        self.this_machine_future = AwsFuture(self._session, m.future_fk, self.lock)
        self.this_machine_is_top_level = m.is_top_level
        self.this_machine = C9Machine(self)
        self.this_machine.run()

    @property
    def probes(self):
        self._session.refresh()
        return [self.this_machine_probe] + [
            AwsProbe(m)
            for m in self._session.machines
            if m.machine_id != self.this_machine_id
        ]

    @property
    def machine_data(self):
        self._session.refresh()
        return self._session.machines


def run(name, executable, *args, do_probe=True, timeout=2, sleep_interval=0.1):
    session = db.new_session()
    controller = AwsController(name, executable, session, do_probe=do_probe)
    m = controller.new_machine(args, top_level=True)
    start_time = time.time()

    try:
        controller.run_machine(m)

        while not controller.finished:
            time.sleep(sleep_interval)
            if time.time() - start_time > timeout:
                raise Exception("Timeout waiting for machine to finish")

        if not all(m.state.stopped for m in controller.machine_data):
            raise Exception("Terminated, but not all machines stopped!")

    except Exception as e:
        warnings.warn("Unexpected Exception!! Returning controller for analysis")
        traceback.print_exc()

    return controller


def run_existing(name, executable, session_id, machine_id, do_probe=True):
    """Run an existing session and machine"""
    session = Session.get(session_id)
    controller = AwsController(name, executable, session, do_probe=do_probe)
    m = session.get_machine(machine_id)
    controller.run_machine(m)


# For auto-gen code:
def get_entrypoint(handler):
    """Return a function that will run the given handler"""
    linked = compiler.link(compiler.compile_all(handler), entrypoint_fn=handler.label)

    @wraps(handler)
    def _f(event, context, linked=linked):
        state = LocalState([event, context])
        # FIXME
        machine.run(linked, state)
        return state.ds_pop()

    return _f
