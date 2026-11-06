"""Read-only bootstrap preflight through its public CLI; Docker is the boundary."""
import subprocess

import pytest


@pytest.fixture
def docker(monkeypatch):
    calls = []
    responses = {}
    monkeypatch.setenv("DOCKER_HOST", "ssh://forbidden.example.test")
    monkeypatch.setenv("DOCKER_CONTEXT", "forbidden-context")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/must-not-read")
    def run(command, **kwargs):
        calls.append(command)
        assert command[:3] == ["docker", "--host", "unix:///var/run/docker.sock"]
        assert not set(kwargs["env"]) & {"DOCKER_HOST", "DOCKER_CONTEXT", "GOOGLE_APPLICATION_CREDENTIALS"}
        operation = command[3]
        assert operation in {"version", "container", "volume", "network", "image"}
        assert not set(command) & {"create", "start", "run", "rm", "remove", "prune", "build", "pull", "inspect"}
        value = responses.get(len(calls), "29.9.1\n" if operation == "version" else "")
        if isinstance(value, Exception):
            raise value
        return subprocess.CompletedProcess(command, 0, stdout=value, stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    return calls, responses


def test_unused_project_is_ready_but_not_created(docker, capsys):
    from scripts.check_training_postgres_target import main
    calls, _ = docker
    assert main([]) == 0
    assert len(calls) == 6
    assert capsys.readouterr().out == '{"project": "fama-training-dev", "resources_created": false, "target_available": true}\n'


@pytest.mark.parametrize("collision", [2, 3, 4, 5, 6])
def test_every_collision_fails_closed_without_mutation(docker, capsys, tmp_path, collision):
    from scripts.check_training_postgres_target import main
    calls, responses = docker
    sentinel = tmp_path / "existing-state"
    sentinel.write_bytes(b"existing database and artifacts")
    responses[collision] = "existing-resource\n"
    assert main([]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Training PostgreSQL preflight refused: resource_collision. No resources were created or changed.\n"
    assert len(calls) == collision
    assert sentinel.read_bytes() == b"existing database and artifacts"


@pytest.mark.parametrize("failure", [
    subprocess.CalledProcessError(1, ["docker"], stderr="synthetic-private-diagnostic"),
    subprocess.TimeoutExpired(["docker"], 15, stderr="synthetic-private-diagnostic"),
    FileNotFoundError("synthetic-private-diagnostic"),
])
def test_docker_failures_are_unavailable_not_absence(docker, capsys, failure):
    from scripts.check_training_postgres_target import main
    calls, responses = docker
    responses[1] = failure
    assert main([]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert output.err == "Training PostgreSQL preflight refused: docker_unavailable. No resources were created or changed.\n"
    assert len(calls) == 1


@pytest.mark.parametrize("project", ["fama", "fama-training-dev;echo", "../old", "fama-training-dev-test-nothex"])
def test_unrelated_or_malformed_project_never_reaches_docker(docker, capsys, project):
    from scripts.check_training_postgres_target import main
    calls, _ = docker
    with pytest.raises(SystemExit) as error:
        main(["--project", project])
    assert error.value.code == 2
    assert not calls
    assert project not in capsys.readouterr().err


def test_disposable_project_uses_only_its_own_resource_names(docker, capsys):
    from scripts.check_training_postgres_target import main
    calls, _ = docker
    project = "fama-training-dev-test-" + "a" * 16
    assert main(["--project", project]) == 0
    assert f"label=com.docker.compose.project={project}" in calls[1]
    assert f"name=^/{project}-(db|bootstrap)(-[0-9]+)?$" in calls[2]
    assert f"name=^{project}_training_pgdata$" in calls[3]
    assert f"name=^{project}_bootstrap$" in calls[4]
    assert f"reference={project}-bootstrap:local" in calls[5]
    assert project in capsys.readouterr().out


def test_mid_inventory_failure_is_not_absence(docker, capsys):
    from scripts.check_training_postgres_target import main
    calls, responses = docker
    responses[4] = subprocess.TimeoutExpired(["docker"], 15, stderr="synthetic-private-diagnostic")
    assert main([]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert output.err == "Training PostgreSQL preflight refused: docker_unavailable. No resources were created or changed.\n"
    assert len(calls) == 4
