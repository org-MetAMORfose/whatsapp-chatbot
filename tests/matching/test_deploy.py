import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from matching.deploy import deploy
from matching.package import copy_sources


def test_package_contains_shared_orm_without_bootstrapping_chatbot(tmp_path):
    copy_sources(tmp_path)
    script = """
import sys
sys.path.insert(0, sys.argv[1])
from matching.handler import handler
from app.domain.db import PatientModel
from app.domain.matching import PatientReference
from sqlalchemy.orm import configure_mappers
configure_mappers()
assert 'app.config.settings' not in sys.modules
assert PatientReference(1).patient_id == 1
"""
    subprocess.run([sys.executable, "-I", "-c", script, str(tmp_path)], check=True, cwd=tmp_path)  # noqa: S603
    assert not (tmp_path / "app/config").exists()
    assert not (tmp_path / "matching/deploy.py").exists()


def test_deploy_updates_existing_function_and_preserves_environment():
    client = MagicMock()
    config = {"FunctionName": "matching", "FunctionArn": "arn:aws:lambda:us-east-1:123456789012:function:matching",
              "Runtime": "python3.13", "Architectures": ["arm64"], "RevisionId": "revision-1",
              "Environment": {"Variables": {"EXISTING": "keep"}}}
    client.get_function_configuration.return_value = config

    def archive(path: Path, runtime: str, architecture: str) -> Path:
        assert runtime == "python3.13" and architecture == "arm64"
        path.write_bytes(b"zip-artifact")
        return path

    with patch("matching.deploy.build", side_effect=archive):
        deploy(client, "matching", "postgresql+psycopg://test/database")
    client.update_function_code.assert_called_once_with(FunctionName="matching", ZipFile=b"zip-artifact", RevisionId="revision-1")
    client.update_function_configuration.assert_called_once_with(FunctionName="matching", Handler="matching.handler.handler",
        Environment={"Variables": {"EXISTING": "keep", "MATCHING_DATABASE_URL": "postgresql+psycopg://test/database"}}, RevisionId="revision-1")
    assert client.get_waiter.return_value.wait.call_count == 2
    client.create_function.assert_not_called()


def test_deploy_requires_settings_before_aws_operations():
    client = MagicMock()
    with pytest.raises(ValueError):
        deploy(client, "", "")
    client.get_function_configuration.assert_not_called()
