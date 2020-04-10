"""Python File -> C9 Executable File"""

import importlib
import logging
import os
import tempfile
from os.path import basename, dirname, join, normpath, splitext
import sys
from shutil import copy, copytree
import glob

from . import compiler
from .lang import Func
from .machine import c9e
from .service import Service
from .synthesiser.synthstate import SynthState
from .constants import (
    LAMBDA_DIRNAME,
    HANDLER_MODULE,
    FN_HANDLE_NEW,
    FN_HANDLE_EXISTING,
    HANDLE_NEW,
    HANDLE_EXISTING,
    SRC_PATH,
    LIB_PATH,
    EXE_PATH,
)


class PackerError(Exception):
    """Error packing a handler or service"""


# https://pymotw.com/3/importlib/
def _import_module(path):
    logging.info(f"importing {path}")
    try:
        # UGLYyyyy
        if os.getcwd() not in sys.path:
            sys.path.append(os.getcwd())
        m = importlib.import_module(path)
    except Exception as e:
        raise PackerError(f"Could not import {path}") from e
    return m


def pack_handler(handler_file: str, handler_attr: str, dest: str, verbose=False):
    """Try to import handler from"""
    m = _import_module(handler_file)
    exe_name = m.__name__ if handler_attr == "main" else handler_attr
    handler_fn = getattr(m, handler_attr)

    if not isinstance(handler_fn, Func):
        raise PackerError(f"Not a Func: '{handler_attr}' in {handler_file}")

    try:
        executable = compiler.link(compiler.compile_all(handler_fn), exe_name)
        c9e.dump(executable, dest)
    except Exception as e:
        raise PackerError from e


def pack_deployment(
    service_file: str,
    attr: str,
    package: str,
    *,
    build_d: str = None,
    libs: str = None,
    dev_pipeline=False,
    verbose=False,
):
    """Pack a service for deployment """
    m = _import_module(service_file)
    service = getattr(m, attr)

    if not build_d:
        build_d = attr.lower()

    if not isinstance(service, Service):
        raise PackerError(f"Not a Service: '{attr}' in {service_file}")

    try:
        pack_lambda_deployment(
            join(build_d, LAMBDA_DIRNAME), service, package, libs, verbose=verbose
        )
        pack_iac(build_d, service, dev_pipeline, verbose=verbose)
    except Exception as e:
        raise PackerError from e


def pack_iac(build_d: str, service: Service, dev_pipeline, verbose=False):
    handlers = [h[1] for h in service.handlers]  # (name, handler) tuple
    resources = compiler.get_resources_set(handlers)
    state = SynthState(service.name, resources, [], [])

    pipeline = service.dev_pipeline if dev_pipeline else service.prod_pipeline

    if verbose:
        print("Resources:\n - " + "\n - ".join(map(str, resources)))

    for synth in pipeline:
        state = synth(state)

    if state.resources:
        warnings.warn(f"Some resources were not synthesised! {state.resources}")

    if verbose:
        print("IAC:\n - " + "\n - ".join(map(str, state.iac)))

    state.gen_iac(build_d)


def pack_lambda_deployment(
    build_d: str, service: Service, package: str, libs: str, *, verbose=False
):
    """Build the lambda source component of the deploy object"""

    # --> C9 Executables
    os.makedirs(join(build_d, EXE_PATH), exist_ok=True)
    for name, handler in service.handlers:
        executable = compiler.link(
            compiler.compile_all(handler), name, entrypoint_fn=handler.label
        )
        exe_dest = join(build_d, EXE_PATH, name + "." + c9e.FILE_EXT)
        c9e.dump(executable, exe_dest)

    # --> Lambda entrypoint
    with open(join(build_d, f"{HANDLER_MODULE}.py"), "w") as f:
        f.write(LAMBDA_MAIN)

    # --> Python libs
    if libs:
        copytree(libs, join(build_d, LIB_PATH), dirs_exist_ok=True)

    # --> Main package Python src (for Foreign calls)
    copytree(package, join(build_d, SRC_PATH, basename(package)), dirs_exist_ok=True)


def copy_all(root, path, dest_path):
    full_path = join(root, path)
    if os.path.isfile(full_path):
        copy(full_path, join(dest_path, basename(path)))
    else:
        copytree(
            full_path, join(dest_path, basename(normpath(path))), dirs_exist_ok=True,
        )


LAMBDA_MAIN = f"""
import sys

sys.path.append("{SRC_PATH}")
sys.path.append("{LIB_PATH}")

import c9.controllers.ddb
import c9.executors.awslambda

def {FN_HANDLE_EXISTING}(event, context):
    run_method = c9.controllers.ddb.run_existing
    return c9.executors.awslambda.handle_existing(run_method, event, context)

def {FN_HANDLE_NEW}(event, context):
    run_method = c9.controllers.ddb.run
    return c9.executors.awslambda.handle_new(run_method, event, context)
"""