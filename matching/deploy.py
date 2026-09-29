"""Update an existing Lambda. No infrastructure provisioning or database access."""
import os
import tempfile
from pathlib import Path
from typing import Any

import boto3

from matching.package import build


def deploy(client: Any, name: str, database_url: str) -> None:
    if not name or not database_url:
        raise ValueError("Set MATCHING_LAMBDA_NAME and MATCHING_DATABASE_URL")
    config = client.get_function_configuration(FunctionName=name)
    if config.get("PackageType", "Zip") != "Zip":
        raise ValueError("The existing Lambda must use a ZIP package")
    # A qualified ARN/alias cannot be updated as a function.
    if name != config["FunctionName"] and name != config["FunctionArn"]:
        raise ValueError("Use the function name or unqualified ARN, not an alias/version")
    with tempfile.TemporaryDirectory(prefix="matching-deploy-") as directory:
        archive = build(Path(directory) / "matching.zip", config["Runtime"], config["Architectures"][0])
        client.update_function_code(FunctionName=name, ZipFile=archive.read_bytes(), RevisionId=config["RevisionId"])
    waiter = client.get_waiter("function_updated_v2")
    waiter.wait(FunctionName=name)
    config = client.get_function_configuration(FunctionName=name)
    variables = dict(config.get("Environment", {}).get("Variables", {}))
    variables["MATCHING_DATABASE_URL"] = database_url
    client.update_function_configuration(FunctionName=name, Handler="matching.handler.handler",
        Environment={"Variables": variables}, RevisionId=config["RevisionId"])
    waiter.wait(FunctionName=name)
    print("Matching Lambda updated successfully")


if __name__ == "__main__":
    deploy(boto3.client("lambda", region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")),
        os.environ["MATCHING_LAMBDA_NAME"], os.environ["MATCHING_DATABASE_URL"])
