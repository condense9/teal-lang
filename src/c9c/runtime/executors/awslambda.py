import json
import logging

from ...lambda_utils import get_lambda_client

logging.basicConfig(level=logging.INFO)


class LambdaRunner:
    def __init__(self, fn_name):
        self.fn_name = fn_name

    def run(
        self, runner, executable_name, searchpath, session_id, machine_id, do_probe
    ):
        assert runner is self
        client = get_lambda_client()
        payload = dict(
            lambda_name=self.fn_name,
            executable_name=executable_name,
            searchpath=searchpath,
            session_id=session_id,
            machine_id=machine_id,
            do_probe=do_probe,
        )
        res = client.invoke(
            # --
            FunctionName=self.fn_name,
            InvocationType="Event",
            Payload=json.dumps(payload),
        )
        if res["StatusCode"] != 202 or "FunctionError" in res:
            err = res["Payload"].read()
            # TODO retry!
            raise Exception(f"Invoke lambda failed {err}")


# Input: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format
def handler(run_controller, event, context):
    """Handle the AWS lambda event for an existing session, returning a JSON response"""
    logging.info(f"Invoked - {event}")
    executor = LambdaRunner(event["lambda_name"])
    controller = run_controller(
        executor,
        event["executable_name"],
        event["searchpath"],
        event["session_id"],
        event["machine_id"],
        event["do_probe"],
    )
    if controller.finished:
        return json.dumps(
            dict(
                session_id=event["session_id"],
                machine_id=event["machine_id"],
                finished=True,
                result=controller.result,
            )
        )
    else:
        return json.dumps(
            dict(
                session_id=event["session_id"],
                machine_id=event["machine_id"],
                finished=False,
            )
        )