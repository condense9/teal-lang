import json
import logging
import os
import time

import boto3
import botocore

from .. import tealparser
from ..controllers import ddb as ddb_controller
from ..controllers import ddb_model as db
from ..machine import TlMachine

RESUME_FN_NAME = os.environ.get("RESUME_FN_NAME", "resume")

LOG = logging.getLogger(__name__)

if os.environ.get("ENABLE_LOGGING", False):
    logging.basicConfig(level=logging.INFO)


def get_lambda_client():
    region = os.environ.get("TL_REGION", None)

    return boto3.client(
        "lambda",
        region_name=region,
        config=botocore.config.Config(retries={"max_attempts": 0}),
    )


class Invoker:
    def __init__(self, data_controller):
        self.data_controller = data_controller
        self.resume_fn_name = RESUME_FN_NAME
        self.exception = None

    def invoke(self, vmid, run_async=True):
        client = get_lambda_client()
        event = dict(
            # --
            session_id=self.data_controller.session.session_id,
            vmid=vmid,
        )
        res = client.invoke(
            # --
            FunctionName=self.resume_fn_name,
            InvocationType="Event",
            Payload=json.dumps(event),
        )
        if res["StatusCode"] != 202 or "FunctionError" in res:
            err = res["Payload"].read()
            # TODO retry!
            raise Exception(f"Invoke lambda {self.resume_fn_name} failed {err}")


# These are Lambda handlers, and maybe should be somewhere else:


def success(code=200, **body_data):
    """Return successfully"""
    return dict(
        statusCode=code,
        isBase64Encoded=False,
        # https://www.serverless.com/blog/cors-api-gateway-survival-guide/
        headers={
            "Access-Control-Allow-Origin": "*",  # Required for CORS
            "Access-Control-Allow-Credentials": True,
        },
        body=json.dumps(body_data),
    )


def fail(msg, code=400, **body_data):
    """Return an error message"""
    # 400 = client error
    # 500 = server error
    return dict(
        statusCode=code,
        isBase64Encoded=False,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": True,
        },
        body=json.dumps({"message": msg, **body_data}),
    )


def resume(event, context):
    """Handle the AWS lambda event for an existing session"""
    session_id = event["session_id"]
    vmid = event["vmid"]

    session = db.Session.get(session_id)
    lock = db.SessionLocker(session)
    controller = ddb_controller.DataController(session, lock)
    invoker = Invoker(controller)

    machine = TlMachine(vmid, invoker)
    try:
        machine.run()
    except Exception as exc:
        with lock:
            session.machines[vmid].exception = str(exc)
        raise

    return success(
        session_id=session_id,
        vmid=vmid,
        finished=controller.finished,
        result=controller.result,
    )


def new_apigw(event, context):
    """API gateway interface to create a new session"""
    try:
        body = json.loads(event["body"])
    except (KeyError, TypeError, json.decoder.JSONDecodeError):
        return fail("No event body")

    return new(body, context)


def new(event, context):
    """Create a new session - event is a simple payload"""
    function = event.get("function", "main")
    args = event.get("args", [])
    check_period = event.get("check_period", 1)
    wait_for_finish = event.get("wait_for_finish", True)
    code = event.get("code", None)
    timeout = event.get("timeout", None)
    timeout = timeout if timeout else int(os.getenv("FIXED_TEAL_TIMEOUT", 5))

    session = db.new_session()

    if code:
        try:
            toplevel = tealparser.evaluate_toplevel(code)
            exe = tealparser.make_exe(toplevel)
        except Exception as exc:
            return fail(f"Error compiling code:\n{exc}")

        try:
            session.executable = exe.serialise()
            session.save()
            LOG.info("Set session code")
        except Session.UpdateError:
            return fail("Error saving code")

    try:
        args = [tealparser.read_exp(arg) for arg in args]
    except:
        return fail("Could not parse args")

    lock = db.SessionLocker(session)
    controller = ddb_controller.DataController(session, lock)
    invoker = Invoker(controller)
    vmid = controller.new_machine(args, function, is_top_level=True)

    try:
        TlMachine(vmid, invoker).run()
    except Exception as exc:
        with lock:
            session.machines[vmid].exception = str(exc)
        return fail("Runtime error", session_id=session.session_id)

    if wait_for_finish:
        start_time = time.time()
        while not controller.finished:
            time.sleep(check_period)
            if time.time() - start_time > timeout:
                return fail("Timeout waiting for finish", session_id=session.session_id)

    return success(
        session_id=session.session_id,
        vmid=vmid,
        finished=controller.finished,
        result=controller.result,
    )


def set_exe(event, context):
    """Set the executable for the base session"""
    db.init_base_session()
    content = event["content"]
    toplevel = tealparser.evaluate_toplevel(content)
    exe = tealparser.make_exe(toplevel)
    db.set_base_exe(exe)
    return success(
        # --
        message="Base Executable set successfully"
    )


def set_session_exe(event, context):
    """Set the executable for the specified session session"""
    session_id = event.get("session_id", None)
    content = event.get("content", None)

    if not content:
        return fail("No Teal code")

    if not session_id:
        return fail("No session ID")

    try:
        session = db.Session.get(session_id)
    except Session.DoesNotExist:
        return fail("Couldn't find that session")

    try:
        toplevel = tealparser.evaluate_toplevel(content)
        exe = tealparser.make_exe(toplevel)
    except:
        return fail("Error compiling code")

    try:
        session.executable = exe.serialise()
        session.save()
    except Session.UpdateError:
        return fail("Error saving code")

    return success(message="Executable set successfully")


def getoutput_apigw(event, context):
    """API Gateway wrapper for getoutput"""
    try:
        body = json.loads(event["body"])
    except (KeyError, TypeError, json.decoder.JSONDecodeError):
        return fail("No event body")

    return getoutput(body, context)


def getoutput(event, context):
    """Get Teal standard output for a session"""
    session_id = event.get("session_id", None)

    # TODO - expire sessions in the DB, or at least disallow querying them

    if not session_id:
        return fail("No session ID")

    try:
        session = db.Session.get(session_id)
    except Session.DoesNotExist:
        return fail("Couldn't find that session")

    output = [m.stdout for m in session.machines]
    exceptions = [m.exception for m in session.machines]

    return success(output=output, exceptions=exceptions, events=[])
